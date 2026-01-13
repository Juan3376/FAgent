"""
Chat SubAgent - 通用对话子智能体（兜底）

职责：
- 处理闲聊、问候
- 通用问答（金融知识等）
- 兜底所有未被其他 SubAgent 处理的问题

特点：
- 直接调用 LLM
- 不需要调用外部工具
- 使用通用的 System Prompt
"""
import time
from typing import AsyncIterator

from .base import BaseSubAgent
from ..router.models import TaskContext, TaskType
from ..services.llm import llm_service
from ..core.prompts import DEFAULT_SYSTEM_PROMPT
from ..core.logging import logger, log_subagent


# Chat SubAgent 专用 Prompt
CHAT_SUBAGENT_PROMPT = """你是 FAgent，一个智能股票交易助手。

你的职责：
- 回答用户关于股票、投资、交易的问题
- 提供市场分析和投资建议
- 解释金融概念和术语
- 友好地处理日常问候和闲聊

注意事项：
- 保持专业、客观
- 投资建议仅供参考，提醒用户注意风险
- 如果不确定，请诚实告知
- 对于需要实时数据的问题，说明需要查询行情

当前任务上下文：
{context_summary}
"""


class ChatSubAgent(BaseSubAgent):
    """
    通用对话子智能体
    
    处理：闲聊、问候、通用问答、兜底
    """
    
    name = "chat"
    
    def __init__(self):
        super().__init__()
        self.llm = llm_service
    
    async def process_stream(self, context: TaskContext) -> AsyncIterator[str]:
        """
        流式处理通用对话
        
        直接调用 LLM，无需外部工具
        """
        start_time = time.time()
        log_subagent.start("ChatSubAgent", context.task_type.value, context)
        
        # 构建消息
        messages = self._build_messages(context)
        
        # 记录 LLM 调用（使用动态模型）
        model = context.model
        log_subagent.llm_call(model=model or "default", messages_count=len(messages), temperature=0.7)
        
        # 流式调用 LLM（传递 model 参数）
        chunk_count = 0
        for chunk in self.llm.chat_completion_stream(
            messages=messages,
            temperature=0.7,
            model=model,
        ):
            chunk_count += 1
            yield chunk
        
        # 记录完成
        duration = time.time() - start_time
        log_subagent.llm_stream(chunk_count=chunk_count, duration=duration)
        log_subagent.done("ChatSubAgent", duration)
    
    async def process(self, context: TaskContext) -> str:
        """
        非流式处理通用对话
        """
        logger.debug(f"ChatSubAgent.process | task_type={context.task_type.value}")
        
        # 构建消息
        messages = self._build_messages(context)
        
        # 非流式调用 LLM（传递 model 参数）
        response = self.llm.chat_completion(
            messages=messages,
            temperature=0.7,
            model=context.model,
        )
        
        return response.choices[0].message.content
    
    def _build_messages(self, context: TaskContext) -> list:
        """构建 LLM 消息列表"""
        # System Prompt（包含上下文信息）
        system_prompt = CHAT_SUBAGENT_PROMPT.format(
            context_summary=context.context_summary or "无特殊上下文"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context.query},
        ]
        
        return messages
    
    def can_handle(self, context: TaskContext) -> bool:
        """ChatSubAgent 可以处理所有任务（兜底）"""
        return True


# 全局实例
chat_subagent = ChatSubAgent()
