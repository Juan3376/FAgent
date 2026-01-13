"""
Chat API - 后端业务接口

后端职责：
1. 接收前端请求
2. 存储用户消息
3. 调用 Agents 服务（HTTP）
4. 存储 AI 回复
5. 返回给前端
6. 异步触发会话总结（首轮对话后）

ID 设计：
- cid: 整数，会话ID
- message_id: 整数，消息ID
"""
import os
import time
import httpx
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json

from ..core.context import set_context, get_context, ctx_logger as logger
from ..core.logging import log_request, log_response, log_call_agents, log_store_message
from ..services.session import session_manager
from ..services.storage import message_storage
from .auth import get_optional_user

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Agents 服务地址
AGENTS_BASE_URL = os.getenv("AGENTS_BASE_URL", "http://localhost:8001")


# ==================== 后台任务 ====================

async def generate_conversation_title(cid: int):
    """
    后台任务：为会话生成标题
    
    在首轮对话完成后调用，自动生成会话标题。
    """
    try:
        # 检查会话是否已有标题
        conversation = session_manager.get_session(cid)
        if conversation is None:
            logger.warning(f"会话不存在，跳过标题生成 | cid={cid}")
            return
        
        if conversation.get("title"):
            logger.debug(f"会话已有标题，跳过生成 | cid={cid} | title={conversation['title']}")
            return
        
        # 获取会话消息
        messages = session_manager.get_messages(cid, limit=6)
        if len(messages) < 2:  # 至少需要一轮对话
            logger.debug(f"消息太少，跳过标题生成 | cid={cid} | count={len(messages)}")
            return
        
        # 调用 Agents 总结服务
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENTS_BASE_URL}/agent/summary/generate",
                json={
                    "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                    "max_messages": 6
                },
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
        
        title = result.get("title", "")
        if title:
            # 更新会话标题
            session_manager.update_session_title(cid, title)
            logger.info(f"会话标题自动生成成功 | cid={cid} | title={title}")
        
    except Exception as e:
        logger.error(f"会话标题生成失败 | cid={cid} | error={str(e)}")


# ==================== 请求/响应模型 ====================

class ChatSendRequest(BaseModel):
    """聊天请求模型"""
    cid: int  # 会话ID
    user_message: str  # 用户消息
    user_message_metadata: Optional[Dict[str, Any]] = None
    
    # LLM 参数
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    history_limit: Optional[int] = None
    model: Optional[str] = None  # 动态模型选择（如 mimo-v2-flash, glm-4.5-air）


class ChatSendResponse(BaseModel):
    """聊天响应模型"""
    content: str
    cid: int
    user_message_id: int
    assistant_message_id: int


class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CreateSessionResponse(BaseModel):
    """创建会话响应"""
    cid: int
    title: Optional[str] = None
    message: str = "Session created successfully"


class UpdateConversationRequest(BaseModel):
    """更新会话请求"""
    title: str


# ==================== 核心业务接口 ====================

@router.post("/send", response_model=ChatSendResponse)
async def chat_send(request: ChatSendRequest):
    """
    发送消息接口（非流式）
    
    流程：
    1. 后端：存储用户消息
    2. 后端：构建 messages，调用 Agents 服务
    3. 后端：存储 AI 回复
    4. 返回给前端
    """
    set_context(cid=str(request.cid))
    logger.info("/send 请求")
    
    try:
        # 1. 存储用户消息
        user_message_id = session_manager.add_message(
            cid=request.cid,
            role="user",
            content=request.user_message,
            metadata=request.user_message_metadata
        )
        logger.debug(f"用户消息已落库 | user_message_id={user_message_id}")
        
        # 2. 构建 messages 列表
        history = message_storage.get_history_before_message(
            cid=request.cid,
            before_message_id=user_message_id,
            limit=request.history_limit
        )
        messages = [{"role": msg["role"], "content": msg["content"]} for msg in history]
        messages.append({"role": "user", "content": request.user_message})
        
        # 3. 调用 Agents 服务
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENTS_BASE_URL}/agent/chat/completion",
                json={
                    "messages": messages,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens
                },
                timeout=60.0
            )
            response.raise_for_status()
            result = response.json()
        
        content = result["content"]
        
        # 4. 存储 AI 回复
        assistant_message_id = session_manager.add_message(
            cid=request.cid,
            role="assistant",
            content=content
        )
        logger.debug(f"AI 回复已落库 | assistant_message_id={assistant_message_id}")
        
        return ChatSendResponse(
            content=content,
            cid=request.cid,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id
        )
    except httpx.HTTPError as e:
        logger.error(f"调用 Agents 服务失败 | error={str(e)}")
        raise HTTPException(status_code=502, detail=f"Agents service error: {str(e)}")
    except Exception as e:
        logger.error(f"/send 错误 | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/stream")
async def chat_send_stream(request: ChatSendRequest):
    """
    发送消息接口（流式）
    
    流程：
    1. 后端：存储用户消息
    2. 后端：构建 messages，调用 Agents 服务（流式）
    3. 后端：接收流式结果，转发给前端
    4. 后端：存储 AI 回复
    """
    start_time = time.time()
    set_context(cid=str(request.cid))
    
    # 记录请求日志
    log_request(
        method="POST",
        path="/api/chat/send/stream",
        body={"cid": request.cid, "user_message": request.user_message[:100], "history_limit": request.history_limit},
        cid=request.cid,
    )
    
    try:
        # 1. 存储用户消息
        user_message_id = session_manager.add_message(
            cid=request.cid,
            role="user",
            content=request.user_message,
            metadata=request.user_message_metadata
        )
        log_store_message(cid=request.cid, role="user", message_id=user_message_id, content_length=len(request.user_message))
        
        # 2. 构建 messages 列表
        history = message_storage.get_history_before_message(
            cid=request.cid,
            before_message_id=user_message_id,
            limit=request.history_limit
        )
        messages = [{"role": msg["role"], "content": msg["content"]} for msg in history]
        messages.append({"role": "user", "content": request.user_message})
        
        logger.debug(f"[HISTORY] cid={request.cid} | loaded={len(history)} messages")
        
        # 捕获参数
        cid = request.cid
        user_message = request.user_message
        history_limit = request.history_limit
        model = request.model
        
        async def generate():
            """SSE 事件生成器"""
            full_content = ""
            assistant_message_id = None
            stream_start = time.time()
            
            try:
                # 3. 调用 Agents Router 服务（流式）
                agents_payload = {
                    "cid": cid,
                    "message_id": user_message_id,
                    "user_message": user_message,
                    "history_limit": history_limit,
                    "model": model,
                }
                log_call_agents(
                    endpoint="/agent/chat/router/stream",
                    payload=agents_payload,
                    cid=cid,
                )
                
                # 获取 request_id 传递给 Agents（cid 已在 body 中）
                ctx = get_context()
                request_headers = {"X-Request-ID": ctx.get("rid", "")}
                
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        f"{AGENTS_BASE_URL}/agent/chat/router/stream",
                        json=agents_payload,
                        headers=request_headers,
                        timeout=120.0  # Router 可能需要更长时间（调用外部数据源）
                    ) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if "content" in data:
                                        full_content += data["content"]
                                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                                    if "error" in data:
                                        logger.error(f"[STREAM_ERROR] cid={cid} | error={data['error']}")
                                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                                        return
                                except json.JSONDecodeError:
                                    pass
                
                stream_duration = time.time() - stream_start
                logger.info(f"[STREAM_COMPLETE] cid={cid} | content_len={len(full_content)} | duration={stream_duration:.3f}s")
                
                # 4. 存储 AI 回复
                assistant_message_id = session_manager.add_message(
                    cid=cid,
                    role="assistant",
                    content=full_content
                )
                log_store_message(cid=cid, role="assistant", message_id=assistant_message_id, content_length=len(full_content))
                
                # 5. 异步触发会话标题生成（首轮对话后）
                asyncio.create_task(generate_conversation_title(cid))
                
                # 发送完成信息
                done_data = json.dumps({
                    "done": True,
                    "cid": cid,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id
                }, ensure_ascii=False)
                yield f"data: {done_data}\n\n"
                yield "data: [DONE]\n\n"
                
                # 记录响应日志
                total_duration = time.time() - start_time
                log_response(
                    method="POST",
                    path="/api/chat/send/stream",
                    status_code=200,
                    duration=total_duration,
                    cid=cid,
                )
                
            except Exception as e:
                logger.error(f"[STREAM_ERROR] cid={cid} | error={str(e)}")
                error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield f"data: {error_data}\n\n"
                
                log_response(
                    method="POST",
                    path="/api/chat/send/stream",
                    status_code=500,
                    duration=time.time() - start_time,
                    cid=cid,
                    error=str(e),
                )
        
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
        logger.error(f"[REQ_ERROR] /send/stream | cid={request.cid} | error={str(e)}")
        log_response(
            method="POST",
            path="/api/chat/send/stream",
            status_code=500,
            duration=time.time() - start_time,
            cid=request.cid,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/router/stream")
async def chat_send_router_stream(request: ChatSendRequest):
    """
    🆕 发送消息接口（Router 模式，流式）
    
    使用 MainRouter 进行多 Agent 路由：
    1. 分析用户意图
    2. 路由到合适的 SubAgent（Market/Chat）
    3. 流式透传 SubAgent 的输出
    
    适用于：需要调用行情工具等外部能力的场景
    """
    set_context(cid=str(request.cid))
    logger.info("/send/router/stream 请求")
    
    try:
        # 1. 存储用户消息
        user_message_id = session_manager.add_message(
            cid=request.cid,
            role="user",
            content=request.user_message,
            metadata=request.user_message_metadata
        )
        logger.debug(f"用户消息已落库 | user_message_id={user_message_id}")
        
        # 捕获参数
        cid = request.cid
        user_message = request.user_message
        history_limit = request.history_limit
        
        async def generate():
            """SSE 事件生成器"""
            full_content = ""
            assistant_message_id = None
            
            try:
                # 2. 调用 Agents Router 服务（流式）
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        f"{AGENTS_BASE_URL}/agent/chat/router/stream",
                        json={
                            "cid": cid,
                            "message_id": user_message_id,
                            "user_message": user_message,
                            "history_limit": history_limit or 10
                        },
                        timeout=120.0  # Router 模式可能需要更长时间
                    ) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if "content" in data:
                                        full_content += data["content"]
                                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                                    if "error" in data:
                                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                                        return
                                except json.JSONDecodeError:
                                    pass
                
                # 3. 存储 AI 回复
                assistant_message_id = session_manager.add_message(
                    cid=cid,
                    role="assistant",
                    content=full_content
                )
                logger.debug(f"AI 回复已落库 | assistant_message_id={assistant_message_id}")
                
                # 4. 异步触发会话标题生成
                asyncio.create_task(generate_conversation_title(cid))
                
                # 发送完成信息
                done_data = json.dumps({
                    "done": True,
                    "cid": cid,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id
                }, ensure_ascii=False)
                yield f"data: {done_data}\n\n"
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                logger.error(f"/send/router/stream 生成错误 | error={str(e)}")
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
        logger.error(f"/send/router/stream 请求错误 | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 会话管理接口 ====================

@router.post("/session/create", response_model=CreateSessionResponse)
async def create_session(
    request: CreateSessionRequest = None,
    current_user: Optional[dict] = Depends(get_optional_user)
):
    """
    创建新会话
    
    如果已登录，会话将关联到当前用户；否则创建匿名会话
    """
    if request is None:
        request = CreateSessionRequest()
    
    user_id = current_user["id"] if current_user else None
    
    cid = session_manager.create_session(
        title=request.title,
        metadata=request.metadata,
        user_id=user_id
    )
    return CreateSessionResponse(cid=cid, title=request.title)


@router.get("/conversation/{cid}")
async def get_conversation(cid: int):
    """获取完整会话记录（包含所有消息）"""
    conversation = session_manager.get_conversation_with_messages(cid)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation {cid} not found")
    return conversation


@router.get("/conversation/{cid}/messages")
async def get_conversation_messages(cid: int, limit: Optional[int] = None):
    """获取会话的消息列表"""
    session = session_manager.get_session(cid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Conversation {cid} not found")
    
    messages = session_manager.get_messages(cid, limit=limit)
    return {
        "cid": cid,
        "messages": messages,
        "count": len(messages)
    }


@router.get("/conversation/{cid}/history")
async def get_conversation_history(
    cid: int,
    before_message_id: int,
    limit: Optional[int] = None
):
    """获取指定消息之前的历史消息"""
    messages = session_manager.get_history_before_message(cid, before_message_id, limit)
    return {
        "cid": cid,
        "before_message_id": before_message_id,
        "messages": messages,
        "count": len(messages)
    }


@router.patch("/conversation/{cid}")
async def update_conversation(cid: int, request: UpdateConversationRequest):
    """
    更新会话信息（如标题）
    
    用于：
    - 手动重命名会话
    - 自动生成的会话总结
    """
    session = session_manager.get_session(cid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Conversation {cid} not found")
    
    success = session_manager.update_session_title(cid, request.title)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update conversation")
    
    return {"message": "Conversation updated successfully", "cid": cid, "title": request.title}


@router.delete("/conversation/{cid}")
async def delete_conversation(cid: int):
    """删除会话及其所有消息"""
    success = session_manager.delete_session(cid)
    if not success:
        raise HTTPException(status_code=404, detail=f"Conversation {cid} not found")
    return {"message": "Conversation deleted successfully", "cid": cid}


@router.post("/conversation/{cid}/clear")
async def clear_conversation(cid: int):
    """清空会话消息（保留会话）"""
    session = session_manager.get_session(cid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Conversation {cid} not found")
    
    session_manager.clear_session(cid)
    return {"message": "Conversation cleared successfully", "cid": cid}


@router.get("/conversations")
async def list_conversations(
    limit: Optional[int] = None, 
    offset: int = 0,
    current_user: Optional[dict] = Depends(get_optional_user)
):
    """
    列出会话
    
    如果已登录，只返回当前用户的会话；否则返回所有匿名会话（user_id=None）
    """
    user_id = current_user["id"] if current_user else None
    conversations = session_manager.list_sessions(limit=limit, offset=offset, user_id=user_id)
    return {
        "conversations": conversations,
        "count": len(conversations)
    }


# ==================== 模型配置接口 ====================

@router.get("/models")
async def get_available_models():
    """
    获取可用的 LLM 模型列表
    
    从 Agents 服务获取配置，前端根据返回动态渲染下拉框
    
    Returns:
        {
            "models": [{"id": "...", "name": "...", "description": "..."}],
            "default": "默认模型ID"
        }
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AGENTS_BASE_URL}/agent/chat/models")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to get models from Agents: {e}")
        # 返回默认配置作为 fallback
        return {
            "models": [
                {"id": "mimo-v2-flash", "name": "Mimo V2 Flash", "description": "默认模型"}
            ],
            "default": "mimo-v2-flash"
        }
