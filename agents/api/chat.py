"""
Agents Chat API - 对话接口（流式和非流式）

Agents 服务对外接口：
- 新接口：使用 Router 进行多 Agent 路由
- 旧接口：纯 LLM 调用（保持兼容）

接口：
- POST /agent/chat/router/stream - 🆕 Router 流式（推荐）
- POST /agent/chat/completion - 非流式（旧）
- POST /agent/chat/stream - 流式（旧）
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Union, Any
import json
import asyncio

from ..services.chat_agent import chat_agent
from ..services.llm import llm_service, AVAILABLE_MODELS
from ..core.prompts import DEFAULT_SYSTEM_PROMPT
from ..core.context import set_context
from ..router import main_router

router = APIRouter(prefix="/agent/chat", tags=["agent-chat"])


# ==================== 请求/响应模型 ====================

class Message(BaseModel):
    """消息模型"""
    role: str  # user, assistant, system
    content: Union[str, List[Dict[str, Any]]]


class AgentChatRequest(BaseModel):
    """Agent 聊天请求模型"""
    # 消息列表（必须提供）
    messages: List[Message]
    
    # LLM 参数
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    reasoning: Optional[bool] = False
    
    # 自定义 System Prompt（可选，覆盖默认）
    system_prompt: Optional[str] = None


class AgentChatResponse(BaseModel):
    """Agent 聊天响应模型"""
    content: str
    model: Optional[str] = None


# ==================== 核心接口 ====================

@router.post("/completion", response_model=AgentChatResponse)
async def agent_chat_completion(request: AgentChatRequest):
    """
    非流式聊天接口
    
    接收 messages 列表，返回 AI 回复。
    纯 LLM 调用，不涉及存储。
    """
    try:
        # 构建 messages
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # 使用 system_prompt（默认使用 DEFAULT_SYSTEM_PROMPT）
        system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT
        messages.insert(0, {"role": "system", "content": system_prompt})
        
        # 调用 LLM
        kwargs = {}
        if request.reasoning:
            kwargs["reasoning"] = {"enabled": True}
        
        response = llm_service.chat_completion(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            **kwargs
        )
        
        return AgentChatResponse(
            content=response.choices[0].message.content,
            model=response.model
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def agent_chat_stream(request: AgentChatRequest):
    """
    流式聊天接口（SSE）
    
    接收 messages 列表，返回流式 AI 回复。
    纯 LLM 调用，不涉及存储。
    """
    try:
        # 构建 messages
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # 使用 system_prompt（默认使用 DEFAULT_SYSTEM_PROMPT）
        system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT
        messages.insert(0, {"role": "system", "content": system_prompt})
        
        # 准备 LLM 参数
        kwargs = {}
        if request.reasoning:
            kwargs["reasoning"] = {"enabled": True}
        
        temperature = request.temperature
        max_tokens = request.max_tokens
        
        def generate():
            """SSE 事件生成器"""
            try:
                for chunk in llm_service.chat_completion_stream(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                ):
                    data = json.dumps({"content": chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                
                # 发送完成信号
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield f"data: {error_data}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 新接口：Router 模式 ====================

class RouterChatRequest(BaseModel):
    """Router 聊天请求模型"""
    cid: int                          # 会话 ID
    message_id: int                   # 当前消息 ID（用于获取历史）
    user_message: str                 # 用户消息
    history_limit: Optional[int] = 10 # 历史消息限制
    model: Optional[str] = None       # 动态模型选择（如 mimo-v2-flash, glm-4.5-air）


class RouterChatResponse(BaseModel):
    """Router 聊天响应模型"""
    content: str
    route: Optional[str] = None       # 路由到哪个 SubAgent


@router.post("/router/stream")
async def router_chat_stream(request: RouterChatRequest):
    """
    🆕 Router 流式聊天接口（推荐）
    
    使用 MainRouter 进行多 Agent 路由：
    1. 分析用户意图
    2. 路由到合适的 SubAgent（Market/Chat）
    3. 流式透传 SubAgent 的输出
    
    适用于：需要调用行情工具等外部能力的场景
    """
    # 设置 cid 到上下文（用于日志追踪）
    set_context(cid=str(request.cid))
    
    try:
        async def generate():
            """异步 SSE 生成器"""
            try:
                async for chunk in main_router.process_stream(
                    cid=request.cid,
                    message_id=request.message_id,
                    user_message=request.user_message,
                    history_limit=request.history_limit or 10,
                    model=request.model,
                ):
                    data = json.dumps({"content": chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                
                # 发送完成信号
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield f"data: {error_data}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/router/completion", response_model=RouterChatResponse)
async def router_chat_completion(request: RouterChatRequest):
    """
    🆕 Router 非流式聊天接口
    
    使用 MainRouter 进行多 Agent 路由（非流式版本）
    """
    try:
        content = await main_router.process(
            cid=request.cid,
            message_id=request.message_id,
            user_message=request.user_message,
            history_limit=request.history_limit or 10,
        )
        
        return RouterChatResponse(content=content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 模型配置接口 ====================

@router.get("/models")
async def get_available_models():
    """
    获取可用的模型列表
    
    Returns:
        List[dict]: 可用模型列表，每个模型包含 id, name, description
    """
    return {
        "models": AVAILABLE_MODELS,
        "default": AVAILABLE_MODELS[0]["id"] if AVAILABLE_MODELS else None
    }

