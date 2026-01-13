"""
LLM Service - 封装 OpenAI SDK 调用

职责：纯 LLM 调用，不涉及存储

注意：环境变量需要在启动服务前设置好（通过 .env 加载或 export）
"""
import os
import sys
import logging
import asyncio
from typing import Optional, Iterator, List, Dict, Any
from openai import OpenAI
from types import SimpleNamespace

# 设置 logger
logger = logging.getLogger(__name__)

# 可用模型列表（供前端展示）
AVAILABLE_MODELS = [
    {
        "id": "mimo-v2-flash",
        "name": "Mimo V2 Flash",
        "description": "小米极速模型，响应快速",
        "model_id": "xiaomi/mimo-v2-flash:free",
    },
    {
        "id": "glm-4.5-air",
        "name": "GLM 4.5 Air",
        "description": "智谱通用模型，能力均衡",
        "model_id": "z-ai/glm-4.5-air:free",
    },
]

# 模型映射表：前端显示名称 -> 实际 Model ID（从 AVAILABLE_MODELS 生成）
MODEL_MAPPING = {m["id"]: m["model_id"] for m in AVAILABLE_MODELS}


class LLMService:
    """LLM 服务类，封装 OpenAI SDK 调用"""
    
    def __init__(self):
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = os.getenv("openrounter_p")
        
        self.mock_mode = False
        self.default_model = os.getenv("LLM_MODEL", "xiaomi/mimo-v2-flash:free")

        if not api_key or api_key == "mock_key":
            logger.warning("OPENROUTER_API_KEY 未设置或为 mock_key，启用 Mock 模式")
            self.mock_mode = True
            self.client = None
        else:
            self.client = OpenAI(
                base_url=base_url,
                api_key=api_key,
            )
            logger.info(f"LLM 服务初始化完成 | default_model={self.default_model} | base_url={base_url}")
    
    def _resolve_model(self, model: Optional[str] = None) -> str:
        """
        解析模型名称
        
        Args:
            model: 前端传入的模型名称（如 mimo-v2-flash）
            
        Returns:
            实际的 Model ID（如 xiaomi/mimo-v2-flash:free）
        """
        if not model:
            return self.default_model
        
        # 如果是映射表中的简称，转换为完整 Model ID
        if model in MODEL_MAPPING:
            resolved = MODEL_MAPPING[model]
            logger.debug(f"模型映射: {model} -> {resolved}")
            return resolved
        
        # 否则直接返回（可能是完整的 Model ID）
        return model
    
    def chat_completion(
        self,
        messages: List[Dict],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs
    ):
        """
        非流式聊天完成
        
        Args:
            messages: 消息列表
            stream: 是否流式（此方法忽略，固定 False）
            temperature: 温度参数
            max_tokens: 最大 token 数
            model: 模型名称（可选，支持简称如 mimo-v2-flash）
            **kwargs: 其他参数
        """
        # 解析模型
        resolved_model = self._resolve_model(model)
        
        if self.mock_mode:
            logger.info(f"Mock LLM 调用 (非流式) | model={resolved_model}")
            content = "这是一个来自 Mock LLM 的回复。后端服务正在运行，但未配置有效的 API Key。"
            
            # 模拟 OpenAI 响应结构
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ],
                model=resolved_model,
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=20,
                    total_tokens=30
                )
            )

        params = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        
        if max_tokens:
            params["max_tokens"] = max_tokens
        
        # 支持 reasoning
        if "reasoning" in kwargs:
            params["extra_body"] = {"reasoning": kwargs["reasoning"]}
        
        logger.debug(f"LLM 非流式请求 | model={resolved_model} | messages_count={len(messages)} | temp={temperature}")
        
        try:
            response = self.client.chat.completions.create(**params)
            
            # 记录 token 使用
            if response.usage:
                logger.info(
                    f"LLM 响应完成 | model={resolved_model} | "
                    f"prompt_tokens={response.usage.prompt_tokens} | "
                    f"completion_tokens={response.usage.completion_tokens} | "
                    f"total_tokens={response.usage.total_tokens}"
                )
            
            return response
        except Exception as e:
            logger.error(f"LLM 调用失败 | model={resolved_model} | error={str(e)}")
            raise
    
    def chat_completion_stream(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Iterator[str]:
        """
        流式聊天完成
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            model: 模型名称（可选，支持简称如 mimo-v2-flash）
            **kwargs: 其他参数
        """
        # 解析模型
        resolved_model = self._resolve_model(model)
        
        if self.mock_mode:
            logger.info(f"Mock LLM 调用 (流式) | model={resolved_model}")
            last_msg = messages[-1]['content'] if messages else "未知"
            response_text = f"【Mock 回复】\n我收到了你的消息：\"{last_msg}\"\n\n后端服务链路正常（Frontend -> Backend -> Agents），但由于未配置有效的 OPENROUTER_API_KEY，Agents 服务当前运行在 Mock 模式。请在 .env 文件中配置 API Key 以接入真实的大模型。"
            import time
            for char in response_text:
                time.sleep(0.02)
                yield char
            return

        params = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        
        if max_tokens:
            params["max_tokens"] = max_tokens
            
        # 支持 reasoning
        if "reasoning" in kwargs:
            params["extra_body"] = {"reasoning": kwargs["reasoning"]}

        logger.debug(f"LLM 流式请求 | model={resolved_model} | messages_count={len(messages)} | temp={temperature}")

        try:
            stream = self.client.chat.completions.create(**params)
            
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"LLM 流式调用失败 | model={resolved_model} | error={str(e)}")
            raise

# 实例化并导出
llm_service = LLMService()
