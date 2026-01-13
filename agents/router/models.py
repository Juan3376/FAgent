"""
Router 数据模型

定义路由决策和任务上下文的数据结构
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum


class RouteType(Enum):
    """路由类型"""
    MARKET = "market"      # 行情相关
    NEWS = "news"          # 新闻相关（未来）
    TRADE = "trade"        # 交易相关（未来）
    CHAT = "chat"          # 通用对话（兜底）


class TaskType(Enum):
    """任务类型"""
    # 行情相关
    GET_QUOTE = "get_quote"           # 查询实时行情
    GET_KLINE = "get_kline"           # 查询 K 线
    SEARCH_STOCK = "search_stock"     # 搜索股票
    ANALYZE_TREND = "analyze_trend"   # 趋势分析
    
    # 通用对话
    GREETING = "greeting"             # 问候
    GENERAL_QA = "general_qa"         # 通用问答
    UNKNOWN = "unknown"               # 未知


@dataclass
class TaskContext:
    """
    任务上下文 - Router 传给 SubAgent 的信息
    
    设计原则：
    - SubAgent 只看这个上下文，不看完整历史
    - Router 负责解析指代、提炼信息
    - 减少 SubAgent 的 Token 消耗
    """
    task_type: TaskType                           # 任务类型
    query: str                                    # 解析后的明确问题（已处理指代）
    params: Dict[str, Any] = field(default_factory=dict)  # 提取的参数
    context_summary: str = ""                     # 相关上下文摘要（可选）
    
    # 原始信息（可选，用于调试）
    original_message: str = ""                    # 原始用户消息
    cid: Optional[int] = None                     # 会话 ID
    model: Optional[str] = None                   # 动态模型选择
    
    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type.value,
            "query": self.query,
            "params": self.params,
            "context_summary": self.context_summary,
            "original_message": self.original_message,
            "cid": self.cid,
            "model": self.model,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TaskContext":
        return cls(
            task_type=TaskType(data.get("task_type", "unknown")),
            query=data.get("query", ""),
            params=data.get("params", {}),
            context_summary=data.get("context_summary", ""),
            original_message=data.get("original_message", ""),
            cid=data.get("cid"),
            model=data.get("model"),
        )


@dataclass
class RouteDecision:
    """
    路由决策结果
    
    Router 分析用户意图后的决策
    """
    route: RouteType                              # 路由到哪个 SubAgent
    task_context: TaskContext                     # 任务上下文
    confidence: float = 1.0                       # 置信度（0-1）
    reasoning: str = ""                           # 决策理由（用于调试）
    
    def to_dict(self) -> dict:
        return {
            "route": self.route.value,
            "task_context": self.task_context.to_dict(),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }
