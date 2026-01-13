"""
Market SubAgent - 行情子智能体

职责：
1. 处理行情相关的查询请求
2. 调用 Market Service 获取数据
3. 使用 LLM 生成分析结果

可处理的任务：
- 查询实时行情（股价、涨跌幅）
- 查询 K 线数据
- 股票搜索
- 简单技术分析

继承 BaseSubAgent，实现统一的 process_stream 接口
"""

import time
from typing import Optional, Dict, Any, List, AsyncIterator
from dataclasses import dataclass
from enum import Enum

from .base import BaseSubAgent
from ..router.models import TaskContext, TaskType
from ..services.llm import llm_service
from ..common.market import (
    market_service,
    StockQuote,
    KLineData,
    StockInfo,
    KLinePeriod,
)
from ..core.logging import logger, log_subagent


class MarketIntent(Enum):
    """行情查询意图"""
    GET_QUOTE = "get_quote"           # 查询实时行情
    GET_KLINE = "get_kline"           # 查询 K 线
    SEARCH_STOCK = "search_stock"     # 搜索股票
    ANALYZE_TREND = "analyze_trend"   # 趋势分析
    UNKNOWN = "unknown"


@dataclass
class MarketQuery:
    """行情查询请求"""
    intent: MarketIntent
    symbol: Optional[str] = None       # 股票代码
    keyword: Optional[str] = None      # 搜索关键词
    period: KLinePeriod = KLinePeriod.DAILY
    count: int = 30                    # K线条数
    
    @classmethod
    def from_dict(cls, data: dict) -> "MarketQuery":
        return cls(
            intent=MarketIntent(data.get("intent", "unknown")),
            symbol=data.get("symbol"),
            keyword=data.get("keyword"),
            period=KLinePeriod(data.get("period", "daily")),
            count=data.get("count", 30),
        )


@dataclass
class MarketResult:
    """行情查询结果"""
    success: bool
    intent: MarketIntent
    data: Optional[Dict[str, Any]] = None  # 原始数据
    summary: str = ""                       # 摘要文本（供 LLM 使用）
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "intent": self.intent.value,
            "data": self.data,
            "summary": self.summary,
            "error": self.error,
        }


MARKET_ANALYSIS_PROMPT = """你是一个专业的股票分析师。基于以下行情数据，为用户提供分析和解读。

行情数据：
{data_summary}

用户问题：{query}

请提供：
1. 数据解读
2. 简要分析
3. 风险提示（如适用）

注意：保持客观专业，投资建议仅供参考。
"""


class MarketSubAgent(BaseSubAgent):
    """
    行情子智能体
    
    处理行情相关的查询请求：
    - 调用 Market Service 获取数据
    - 使用 LLM 生成分析结果
    
    继承 BaseSubAgent，实现统一接口
    """
    
    name = "market"
    
    def __init__(self):
        super().__init__()
        self.service = market_service
        self.llm = llm_service
    
    # ==================== BaseSubAgent 接口实现 ====================
    
    async def process_stream(self, context: TaskContext) -> AsyncIterator[str]:
        """
        流式处理行情任务（BaseSubAgent 接口）
        
        流程：
        1. 根据 TaskContext 获取数据
        2. 使用 LLM 流式生成分析
        """
        start_time = time.time()
        log_subagent.start("MarketSubAgent", context.task_type.value, context)
        
        # 1. 根据任务类型获取数据
        data_result = self._execute_task(context)
        
        if not data_result.success:
            log_subagent.done("MarketSubAgent", time.time() - start_time, success=False)
            yield f"抱歉，{data_result.error}"
            return
        
        # 2. 构建 LLM 消息
        messages = [
            {
                "role": "system",
                "content": MARKET_ANALYSIS_PROMPT.format(
                    data_summary=data_result.summary,
                    query=context.query
                )
            },
            {
                "role": "user",
                "content": context.query
            }
        ]
        
        # 3. 流式调用 LLM 生成分析（使用动态模型）
        model = context.model
        log_subagent.llm_call(model=model or "default", messages_count=len(messages), temperature=0.7)
        
        chunk_count = 0
        for chunk in self.llm.chat_completion_stream(
            messages=messages,
            temperature=0.7,
            model=model,
        ):
            chunk_count += 1
            yield chunk
        
        duration = time.time() - start_time
        log_subagent.llm_stream(chunk_count=chunk_count, duration=duration)
        log_subagent.done("MarketSubAgent", duration)
    
    async def process_from_context(self, context: TaskContext) -> str:
        """
        非流式处理行情任务（BaseSubAgent 接口）
        """
        logger.debug(f"MarketSubAgent.process_from_context | task_type={context.task_type.value}")
        
        # 收集流式输出
        result = ""
        async for chunk in self.process_stream(context):
            result += chunk
        return result
    
    # Period 参数映射（处理 LLM 可能输出的变体）
    PERIOD_MAPPING = {
        "day": "daily",
        "d": "daily",
        "日": "daily",
        "日k": "daily",
        "week": "weekly",
        "w": "weekly",
        "周": "weekly",
        "周k": "weekly",
        "month": "monthly",
        "m": "monthly",
        "月": "monthly",
        "月k": "monthly",
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "60m": "60min",
        "1h": "60min",
    }
    
    def _normalize_period(self, period: str) -> str:
        """
        标准化 period 参数
        
        将 LLM 可能输出的各种变体映射到有效的 KLinePeriod 值
        """
        if not period:
            return "daily"
        
        period_lower = period.lower().strip()
        
        # 先查映射表
        if period_lower in self.PERIOD_MAPPING:
            return self.PERIOD_MAPPING[period_lower]
        
        # 已经是有效值
        valid_periods = ["daily", "weekly", "monthly", "1min", "5min", "15min", "30min", "60min"]
        if period_lower in valid_periods:
            return period_lower
        
        # 默认返回 daily
        logger.warning(f"未知的 period 值: {period}，使用默认值 daily")
        return "daily"
    
    def _execute_task(self, context: TaskContext) -> MarketResult:
        """根据 TaskContext 执行具体任务"""
        task_type = context.task_type
        params = context.params
        
        logger.debug(f"[EXECUTE_TASK] task_type={task_type.value} | params={params}")
        
        try:
            if task_type == TaskType.GET_QUOTE:
                log_subagent.tool_call("market_service.get_quote", {"symbol": params.get("symbol", "")})
                start = time.time()
                result = self._get_quote(params.get("symbol", ""))
                log_subagent.tool_result(
                    "market_service.get_quote",
                    result.success,
                    data=result.summary[:200] if result.summary else None,
                    error=result.error,
                    duration=time.time() - start
                )
                return result
            
            elif task_type == TaskType.GET_KLINE:
                # 标准化 period 参数
                raw_period = params.get("period", "daily")
                normalized_period = self._normalize_period(raw_period)
                
                log_subagent.tool_call("market_service.get_kline", {
                    "symbol": params.get("symbol", ""),
                    "period": normalized_period,
                    "count": params.get("count", 30)
                })
                start = time.time()
                result = self._get_kline(
                    params.get("symbol", ""),
                    KLinePeriod(normalized_period),
                    params.get("count", 30)
                )
                log_subagent.tool_result(
                    "market_service.get_kline",
                    result.success,
                    data=result.summary[:200] if result.summary else None,
                    error=result.error,
                    duration=time.time() - start
                )
                return result
            
            elif task_type == TaskType.SEARCH_STOCK:
                log_subagent.tool_call("market_service.search", {"keyword": params.get("keyword", "")})
                start = time.time()
                result = self._search_stock(params.get("keyword", ""))
                log_subagent.tool_result(
                    "market_service.search",
                    result.success,
                    data=result.summary[:200] if result.summary else None,
                    error=result.error,
                    duration=time.time() - start
                )
                return result
            
            elif task_type == TaskType.ANALYZE_TREND:
                log_subagent.tool_call("market_service.analyze_trend", params)
                start = time.time()
                result = self._analyze_trend(
                    params.get("symbol", ""),
                    params.get("count", 30)
                )
                log_subagent.tool_result(
                    "market_service.analyze_trend",
                    result.success,
                    data=result.summary[:200] if result.summary else None,
                    error=result.error,
                    duration=time.time() - start
                )
                return result
            
            else:
                return MarketResult(
                    success=False,
                    intent=MarketIntent.UNKNOWN,
                    error=f"不支持的任务类型: {task_type.value}"
                )
                
        except Exception as e:
            # 捕获所有异常，返回友好错误
            logger.error(f"[EXECUTE_TASK_ERROR] task={task_type.value} | error={e}")
            return MarketResult(
                success=False,
                intent=MarketIntent.UNKNOWN,
                error=f"执行任务时出错，请稍后重试"
            )
    
    # ==================== 原有接口（兼容旧代码） ====================
    
    def process(self, query: MarketQuery) -> MarketResult:
        """
        处理行情查询（原有接口，保持兼容）
        
        Args:
            query: 查询请求
            
        Returns:
            MarketResult
        """
        logger.debug(f"MarketSubAgent.process | intent={query.intent.value}")
        
        try:
            if query.intent == MarketIntent.GET_QUOTE:
                return self._get_quote(query.symbol)
            
            elif query.intent == MarketIntent.GET_KLINE:
                return self._get_kline(query.symbol, query.period, query.count)
            
            elif query.intent == MarketIntent.SEARCH_STOCK:
                return self._search_stock(query.keyword)
            
            elif query.intent == MarketIntent.ANALYZE_TREND:
                return self._analyze_trend(query.symbol, query.count)
            
            else:
                return MarketResult(
                    success=False,
                    intent=query.intent,
                    error="未知的查询意图",
                )
        except Exception as e:
            logger.error(f"MarketSubAgent 处理失败 | error={e}")
            return MarketResult(
                success=False,
                intent=query.intent,
                error=str(e),
            )
    
    def _get_quote(self, symbol: str) -> MarketResult:
        """获取实时行情"""
        if not symbol:
            return MarketResult(
                success=False,
                intent=MarketIntent.GET_QUOTE,
                error="请提供股票代码",
            )
        
        quote = self.service.get_quote(symbol)
        if quote:
            return MarketResult(
                success=True,
                intent=MarketIntent.GET_QUOTE,
                data=quote.to_dict(),
                summary=quote.summary(),
            )
        else:
            return MarketResult(
                success=False,
                intent=MarketIntent.GET_QUOTE,
                error=f"未能获取 {symbol} 的行情数据",
            )
    
    def _get_kline(
        self, 
        symbol: str, 
        period: KLinePeriod,
        count: int
    ) -> MarketResult:
        """获取 K 线数据"""
        if not symbol:
            return MarketResult(
                success=False,
                intent=MarketIntent.GET_KLINE,
                error="请提供股票代码",
            )
        
        kline = self.service.get_kline(symbol, period, count)
        if kline:
            return MarketResult(
                success=True,
                intent=MarketIntent.GET_KLINE,
                data=kline.to_dict(),
                summary=kline.summary(),
            )
        else:
            return MarketResult(
                success=False,
                intent=MarketIntent.GET_KLINE,
                error=f"未能获取 {symbol} 的 K 线数据",
            )
    
    def _search_stock(self, keyword: str) -> MarketResult:
        """搜索股票"""
        if not keyword:
            return MarketResult(
                success=False,
                intent=MarketIntent.SEARCH_STOCK,
                error="请提供搜索关键词",
            )
        
        results = self.service.search(keyword)
        if results:
            data = [info.to_dict() for info in results]
            summary = f"找到 {len(results)} 只相关股票：" + "、".join(
                f"{r.name}({r.symbol})" for r in results[:5]
            )
            if len(results) > 5:
                summary += f" 等"
            
            return MarketResult(
                success=True,
                intent=MarketIntent.SEARCH_STOCK,
                data={"results": data},
                summary=summary,
            )
        else:
            return MarketResult(
                success=False,
                intent=MarketIntent.SEARCH_STOCK,
                error=f"未找到与 '{keyword}' 相关的股票",
            )
    
    def _analyze_trend(self, symbol: str, days: int = 30) -> MarketResult:
        """
        趋势分析
        
        基于 K 线数据进行简单的趋势分析：
        - 计算均线（MA5, MA10, MA20）
        - 判断趋势方向
        - 识别金叉/死叉
        """
        if not symbol:
            return MarketResult(
                success=False,
                intent=MarketIntent.ANALYZE_TREND,
                error="请提供股票代码",
            )
        
        kline = self.service.get_kline(symbol, KLinePeriod.DAILY, days + 20)
        if not kline or not kline.data:
            return MarketResult(
                success=False,
                intent=MarketIntent.ANALYZE_TREND,
                error=f"未能获取 {symbol} 的 K 线数据",
            )
        
        # 提取收盘价
        closes = [d["close"] for d in kline.data]
        
        # 计算均线
        ma5 = self._calculate_ma(closes, 5)
        ma10 = self._calculate_ma(closes, 10)
        ma20 = self._calculate_ma(closes, 20)
        
        # 判断趋势
        current_price = closes[-1] if closes else 0
        trend = self._determine_trend(current_price, ma5, ma10, ma20)
        
        # 检测金叉/死叉
        signal = self._detect_cross(ma5, ma10)
        
        analysis = {
            "symbol": symbol,
            "current_price": current_price,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "trend": trend,
            "signal": signal,
        }
        
        # 生成摘要
        summary = (
            f"{symbol} 趋势分析：当前价格 {current_price:.2f} 元，"
            f"MA5={ma5:.2f}，MA10={ma10:.2f}，MA20={ma20:.2f}。"
            f"趋势判断：{trend}。"
        )
        if signal:
            summary += f"信号：{signal}。"
        
        return MarketResult(
            success=True,
            intent=MarketIntent.ANALYZE_TREND,
            data=analysis,
            summary=summary,
        )
    
    def _calculate_ma(self, prices: List[float], period: int) -> float:
        """计算移动平均线"""
        if len(prices) < period:
            return 0.0
        return sum(prices[-period:]) / period
    
    def _determine_trend(
        self, 
        price: float, 
        ma5: float, 
        ma10: float, 
        ma20: float
    ) -> str:
        """判断趋势"""
        if price > ma5 > ma10 > ma20:
            return "强势上涨"
        elif price > ma5 > ma10:
            return "上涨趋势"
        elif price > ma5:
            return "短期反弹"
        elif price < ma5 < ma10 < ma20:
            return "强势下跌"
        elif price < ma5 < ma10:
            return "下跌趋势"
        elif price < ma5:
            return "短期回调"
        else:
            return "震荡整理"
    
    def _detect_cross(self, ma_fast: float, ma_slow: float) -> Optional[str]:
        """检测金叉/死叉（简化版，仅比较当前值）"""
        # 实际应比较前后两天，这里简化处理
        if ma_fast > ma_slow * 1.01:  # 快线高于慢线 1% 以上
            return "短期均线金叉"
        elif ma_fast < ma_slow * 0.99:  # 快线低于慢线 1% 以上
            return "短期均线死叉"
        return None
    
    # ==================== 便捷方法 ====================
    
    def quick_quote(self, symbol: str) -> str:
        """快速获取行情摘要"""
        result = self._get_quote(symbol)
        return result.summary if result.success else result.error
    
    def quick_kline(self, symbol: str, days: int = 5) -> str:
        """快速获取 K 线摘要"""
        result = self._get_kline(symbol, KLinePeriod.DAILY, days + 10)
        return result.summary if result.success else result.error
    
    def quick_analysis(self, symbol: str) -> str:
        """快速趋势分析"""
        result = self._analyze_trend(symbol)
        return result.summary if result.success else result.error


# 全局实例
market_subagent = MarketSubAgent()

