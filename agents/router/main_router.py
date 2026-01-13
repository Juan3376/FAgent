"""
MainRouter - 主路由器

整个对话系统的入口点，负责：
1. 维护完整对话历史
2. 意图识别 + 路由决策
3. 提炼任务上下文给 SubAgent
4. 流式透传 SubAgent 的输出（不做二次 LLM 处理）
"""
import os
import sys
import time
import json
import re
from typing import AsyncIterator, Dict, List, Optional, Any

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.storage import message_storage

from .models import TaskContext, TaskType, RouteType, RouteDecision
from ..services.llm import llm_service
from ..subagents import chat_subagent, market_subagent
from ..core.logging import logger, log_router, log_subagent


# 路由决策 Prompt
ROUTER_SYSTEM_PROMPT = """你是一个任务路由器，负责分析用户意图并路由到合适的处理模块。

根据用户消息和对话历史，判断：
1. 这是什么类型的问题
2. 需要路由到哪个处理模块
3. 提取关键参数

【路由类型】
- market: 行情查询、股票分析、K线数据、趋势分析
- chat: 闲聊、问候、通用问答、金融知识解释

【任务类型及参数】
- get_quote: 查询实时行情
  参数: symbol (股票代码，如 "600519")
  
- get_kline: 查询K线数据
  参数: symbol (股票代码), period (周期), count (数量)
  period 有效值: "daily"(日K), "weekly"(周K), "monthly"(月K), "1min", "5min", "15min", "30min", "60min"
  
- search_stock: 搜索股票
  参数: keyword (搜索关键词)
  
- analyze_trend: 趋势分析
  参数: symbol (股票代码)
  
- greeting: 问候（无需参数）
- general_qa: 通用问答（无需参数）

【重要】
1. 解析指代词：如果用户说"那个股票"、"它"等，根据上下文推断具体指什么
2. 提取股票代码：茅台=600519, 平安银行=000001 等
3. 如果无法确定股票代码，可以先搜索
4. 查询最近一周行情时，建议用 get_kline + period="daily" + count=5

输出 JSON 格式：
{
    "route": "market" | "chat",
    "task_type": "get_quote" | "get_kline" | "analyze_trend" | "search_stock" | "greeting" | "general_qa",
    "query": "解析后的明确问题",
    "params": {"symbol": "600519", "period": "daily", "count": 5},
    "context_summary": "相关上下文（如有）",
    "reasoning": "决策理由"
}
"""


class MainRouter:
    """
    主路由器
    
    职责：
    1. 维护对话历史（通过 cid 关联）
    2. 意图识别和路由决策
    3. 上下文提炼
    4. 流式透传 SubAgent 输出
    """
    
    def __init__(self):
        self.llm = llm_service
        
        # 注册 SubAgents
        self.subagents = {
            RouteType.MARKET: market_subagent,
            RouteType.CHAT: chat_subagent,
        }
        
        logger.info("MainRouter 初始化完成")
    
    async def process_stream(
        self,
        cid: int,
        message_id: int,
        user_message: str,
        history_limit: int = 10,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        处理用户消息（流式）- 系统主入口
        
        Args:
            cid: 会话 ID
            message_id: 当前消息 ID（用于获取历史）
            user_message: 用户消息
            history_limit: 历史消息条数限制
            model: 动态模型选择（可选）
            
        Yields:
            流式文本片段
        """
        start_time = time.time()
        
        # 记录请求
        log_router.request(cid=cid, message_id=message_id, user_message=user_message)
        
        # 1. 获取对话历史
        history = self._get_history(cid, message_id, history_limit)
        log_router.history(cid=cid, message_count=len(history), messages=history if len(history) < 10 else None)
        
        # 2. 路由决策
        decision = await self._route(user_message, history)
        log_router.intent(
            route=decision.route.value,
            task=decision.task_context.task_type.value,
            params=decision.task_context.params,
            raw_response=decision.reasoning,
        )
        
        # 3. 获取对应的 SubAgent
        subagent = self.subagents.get(decision.route, self.subagents[RouteType.CHAT])
        subagent_name = subagent.__class__.__name__
        
        # 4. 设置上下文的原始信息
        decision.task_context.original_message = user_message
        decision.task_context.cid = cid
        decision.task_context.model = model
        
        # 记录上下文和分发
        log_router.context(decision.task_context)
        log_router.dispatch(subagent_name, decision.task_context.task_type.value)
        
        # 5. 流式透传 SubAgent 的输出
        try:
            async for chunk in subagent.process_stream(decision.task_context):
                yield chunk
                
            # 记录完成
            duration = time.time() - start_time
            log_router.done(cid=cid, duration=duration, route=decision.route.value)
            
        except Exception as e:
            logger.error(f"[ROUTER_ERROR] cid={cid} | subagent={subagent_name} | error={e}")
            log_router.fallback(f"SubAgent 处理失败: {str(e)}")
            yield f"抱歉，处理请求时出现错误：{str(e)}"
    
    async def process(
        self,
        cid: int,
        message_id: int,
        user_message: str,
        history_limit: int = 10,
    ) -> str:
        """
        处理用户消息（非流式）
        """
        result = ""
        async for chunk in self.process_stream(cid, message_id, user_message, history_limit):
            result += chunk
        return result
    
    def _get_history(
        self,
        cid: int,
        before_message_id: int,
        limit: int = 10
    ) -> List[Dict]:
        """获取对话历史"""
        messages = message_storage.get_history_before_message(cid, before_message_id, limit)
        return [{"role": msg["role"], "content": msg["content"]} for msg in messages]
    
    async def _route(
        self,
        user_message: str,
        history: List[Dict]
    ) -> RouteDecision:
        """
        路由决策
        
        使用 LLM 分析意图并决定路由
        """
        # 构建消息
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        ]
        
        # 添加历史（简化版，只取最近几条）
        if history:
            history_text = "\n".join([
                f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content'][:100]}..."
                if len(m['content']) > 100 else
                f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
                for m in history[-6:]  # 最近 6 条
            ])
            messages.append({
                "role": "user",
                "content": f"【对话历史】\n{history_text}\n\n【当前问题】\n{user_message}"
            })
        else:
            messages.append({
                "role": "user",
                "content": f"【当前问题】\n{user_message}"
            })
        
        # 调用 LLM
        try:
            response = self.llm.chat_completion(
                messages=messages,
                temperature=0.3,  # 低温度，更确定性
            )
            
            content = response.choices[0].message.content
            
            # 解析 JSON
            decision = self._parse_route_response(content, user_message)
            return decision
            
        except Exception as e:
            logger.error(f"路由决策失败 | error={e}")
            # 降级：默认路由到 chat
            return RouteDecision(
                route=RouteType.CHAT,
                task_context=TaskContext(
                    task_type=TaskType.GENERAL_QA,
                    query=user_message,
                ),
                reasoning=f"路由失败，降级到 chat: {str(e)}"
            )
    
    def _parse_route_response(self, content: str, original_message: str) -> RouteDecision:
        """解析 LLM 的路由决策响应"""
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("未找到 JSON")
            
            # 解析路由类型
            route_str = data.get("route", "chat")
            try:
                route = RouteType(route_str)
            except ValueError:
                route = RouteType.CHAT
            
            # 解析任务类型
            task_str = data.get("task_type", "general_qa")
            try:
                task_type = TaskType(task_str)
            except ValueError:
                task_type = TaskType.GENERAL_QA
            
            # 构建 TaskContext
            task_context = TaskContext(
                task_type=task_type,
                query=data.get("query", original_message),
                params=data.get("params", {}),
                context_summary=data.get("context_summary", ""),
            )
            
            return RouteDecision(
                route=route,
                task_context=task_context,
                confidence=1.0,
                reasoning=data.get("reasoning", ""),
            )
            
        except Exception as e:
            logger.warning(f"解析路由响应失败 | error={e} | content={content[:200]}")
            # 使用简单规则降级
            return self._fallback_route(original_message)
    
    def _fallback_route(self, message: str) -> RouteDecision:
        """
        降级路由（当 LLM 解析失败时）
        
        使用简单规则判断
        """
        message_lower = message.lower()
        
        # 行情相关关键词
        market_keywords = [
            "行情", "股票", "股价", "涨", "跌", "k线", "均线",
            "茅台", "银行", "买入", "卖出", "分析", "趋势",
            "600", "000", "300", "查询", "搜索",
        ]
        
        for keyword in market_keywords:
            if keyword in message_lower:
                return RouteDecision(
                    route=RouteType.MARKET,
                    task_context=TaskContext(
                        task_type=TaskType.GENERAL_QA,  # 让 MarketSubAgent 自己判断
                        query=message,
                    ),
                    reasoning=f"规则匹配关键词: {keyword}",
                )
        
        # 默认：通用对话
        return RouteDecision(
            route=RouteType.CHAT,
            task_context=TaskContext(
                task_type=TaskType.GENERAL_QA,
                query=message,
            ),
            reasoning="无匹配关键词，默认 chat",
        )


# 全局实例
main_router = MainRouter()
