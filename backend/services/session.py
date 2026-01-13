"""
会话管理服务 - 管理多轮对话的会话和历史

ID 设计：
- cid: 整数，会话ID，自增
- message_id: 整数，消息ID，自增

消息流程：
1. 用户消息先落库，获取 message_id
2. 用 message_id 过滤历史消息作为上下文
3. 调用 LLM
4. AI 回复落库

消息角色：
- user: 用户消息
- assistant: AI 回复
- system: 系统消息
"""
from typing import Dict, List, Optional, Union
from ..core.context import ctx_logger as logger
from .storage import message_storage, ContentType


class SessionManager:
    """
    会话管理器
    
    使用整数自增 ID：
    - cid: 会话ID
    - message_id: 消息ID
    """
    
    def create_session(
        self,
        title: Optional[str] = None,
        metadata: Optional[Dict] = None,
        user_id: Optional[int] = None
    ) -> int:
        """
        创建新会话
        
        Args:
            title: 会话标题（可选）
            metadata: 会话元数据（可选）
            user_id: 用户ID（可选，用于数据隔离）
        
        Returns:
            cid（整数）
        """
        cid = message_storage.create_conversation(title=title, metadata=metadata, user_id=user_id)
        logger.info(f"SessionManager: 会话创建 | cid={cid} | user_id={user_id} | title={title}")
        return cid
    
    def update_session_title(self, cid: int, title: str) -> bool:
        """
        更新会话标题
        
        Args:
            cid: 会话ID
            title: 新标题
            
        Returns:
            是否更新成功
        """
        success = message_storage.update_conversation_title(cid, title)
        if success:
            logger.info(f"SessionManager: 会话标题更新 | cid={cid} | title={title}")
        return success
    
    def get_session(self, cid: int) -> Optional[Dict]:
        """获取会话信息"""
        return message_storage.get_conversation(cid)
    
    def add_message(
        self,
        cid: int,
        role: str,
        content: Union[str, List, Dict],
        content_type: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> int:
        """
        添加消息到会话
        
        Args:
            cid: 会话ID（整数）
            role: 消息角色 (user, assistant, system)
            content: 消息内容
            content_type: 内容类型
            metadata: 消息元数据
            
        Returns:
            message_id（整数）
        """
        return message_storage.add_message(
            cid=cid,
            role=role,
            content=content,
            content_type=content_type,
            metadata=metadata
        )
    
    def get_message(self, message_id: int) -> Optional[Dict]:
        """获取单条消息"""
        return message_storage.get_message(message_id)
    
    def get_messages(self, cid: int, limit: Optional[int] = None) -> List[Dict]:
        """获取会话的所有消息"""
        return message_storage.get_messages(cid=cid, limit=limit)
    
    def get_history_before_message(
        self,
        cid: int,
        before_message_id: int,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        获取指定消息之前的历史消息
        
        用于构建 LLM 上下文
        """
        return message_storage.get_history_before_message(cid, before_message_id, limit)
    
    def get_messages_for_llm(
        self,
        cid: int,
        before_message_id: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        获取 LLM API 格式的消息列表
        
        Args:
            cid: 会话ID
            before_message_id: 如果提供，获取此消息之前的历史
            limit: 最多返回条数
            
        Returns:
            [{"role": "user/assistant", ...}, ...]
            
        Note:
            System prompt 由 Agent 层处理
        """
        return message_storage.get_messages_for_llm(cid, before_message_id, limit)
    
    def get_conversation_with_messages(self, cid: int) -> Optional[Dict]:
        """获取会话及其所有消息"""
        return message_storage.get_conversation_with_messages(cid)
    
    def update_message_content(
        self,
        message_id: int,
        content: Union[str, List, Dict],
        content_type: Optional[str] = None
    ) -> bool:
        """更新消息内容（用于流式场景追加内容）"""
        return message_storage.update_message_content(message_id, content, content_type)
    
    def update_message_metadata(self, message_id: int, metadata: Dict) -> bool:
        """更新消息 metadata"""
        return message_storage.update_message_metadata(message_id, metadata)
    
    def delete_message(self, message_id: int) -> bool:
        """删除单条消息"""
        return message_storage.delete_message(message_id)
    
    def clear_session(self, cid: int) -> bool:
        """清空会话消息（保留会话）"""
        return message_storage.clear_conversation_messages(cid)
    
    def delete_session(self, cid: int) -> bool:
        """删除会话及其所有消息"""
        return message_storage.delete_conversation(cid)
    
    def list_sessions(
        self, 
        limit: Optional[int] = None, 
        offset: int = 0,
        user_id: Optional[int] = None
    ) -> List[Dict]:
        """
        列出会话
        
        Args:
            limit: 返回条数限制
            offset: 偏移量
            user_id: 用户ID（可选，用于数据隔离）
        """
        return message_storage.list_conversations(limit=limit, offset=offset, user_id=user_id)
    
    def check_conversation_owner(self, cid: int, user_id: int) -> bool:
        """
        检查会话是否属于指定用户
        
        Args:
            cid: 会话ID
            user_id: 用户ID
            
        Returns:
            是否属于该用户
        """
        return message_storage.check_conversation_owner(cid, user_id)


# 全局会话管理器实例
session_manager = SessionManager()
