"""
Auth API - 用户认证接口

提供用户注册、登录和获取当前用户信息的接口。
使用 JWT (JSON Web Token) 进行认证。

接口：
- POST /api/auth/register - 用户注册
- POST /api/auth/login - 用户登录
- GET /api/auth/me - 获取当前用户信息
"""
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr, field_validator
from passlib.context import CryptContext

from ..services.storage import message_storage
from ..core.context import ctx_logger as logger

router = APIRouter(prefix="/api/auth", tags=["auth"])

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", "fagent-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 天过期

# 密码加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ==================== 请求/响应模型 ====================

class RegisterRequest(BaseModel):
    """注册请求模型"""
    username: str
    email: EmailStr
    password: str
    
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 3:
            raise ValueError("用户名至少 3 个字符")
        if len(v) > 20:
            raise ValueError("用户名最多 20 个字符")
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("密码至少 6 个字符")
        return v


class LoginRequest(BaseModel):
    """登录请求模型"""
    username: Optional[str] = None  # 用户名或邮箱
    email: Optional[str] = None
    password: str
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("密码不能为空")
        return v


class AuthResponse(BaseModel):
    """认证响应模型"""
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    """用户信息响应模型"""
    id: int
    username: str
    email: str
    created_at: str


# ==================== 工具函数 ====================

def hash_password(password: str) -> str:
    """密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: int, username: str) -> str:
    """创建 JWT Token"""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析 JWT Token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的 Token")


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    获取当前用户（依赖注入）
    
    从 Authorization Header 中解析 JWT Token，返回用户信息
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")
    
    # 解析 Bearer Token
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证格式")
    
    token = authorization[7:]  # 去掉 "Bearer " 前缀
    
    # 解析 Token
    payload = decode_access_token(token)
    user_id = int(payload.get("sub", 0))
    
    # 获取用户信息
    user = message_storage.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    
    return user


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """
    获取当前用户（可选，不强制认证）
    
    用于兼容未登录用户的场景
    """
    if not authorization:
        return None
    
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None


# ==================== API 接口 ====================

@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    """
    用户注册
    
    创建新用户并返回 JWT Token
    """
    logger.info(f"用户注册请求 | username={request.username} | email={request.email}")
    
    # 检查用户名是否已存在
    if message_storage.get_user_by_username(request.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 检查邮箱是否已存在
    if message_storage.get_user_by_email(request.email):
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    
    # 创建用户
    try:
        password_hash = hash_password(request.password)
        user_id = message_storage.create_user(
            username=request.username,
            email=request.email,
            password_hash=password_hash
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # 生成 Token
    access_token = create_access_token(user_id, request.username)
    
    logger.info(f"用户注册成功 | user_id={user_id} | username={request.username}")
    
    return AuthResponse(
        access_token=access_token,
        user={
            "id": user_id,
            "username": request.username,
            "email": request.email
        }
    )


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """
    用户登录
    
    验证用户名/邮箱和密码，返回 JWT Token
    """
    # 必须提供用户名或邮箱
    if not request.username and not request.email:
        raise HTTPException(status_code=400, detail="请提供用户名或邮箱")
    
    # 根据用户名或邮箱查找用户
    user = None
    if request.username:
        user = message_storage.get_user_by_username(request.username)
    if not user and request.email:
        user = message_storage.get_user_by_email(request.email)
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名/邮箱或密码错误")
    
    # 验证密码
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名/邮箱或密码错误")
    
    # 生成 Token
    access_token = create_access_token(user["id"], user["username"])
    
    logger.info(f"用户登录成功 | user_id={user['id']} | username={user['username']}")
    
    return AuthResponse(
        access_token=access_token,
        user={
            "id": user["id"],
            "username": user["username"],
            "email": user["email"]
        }
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    获取当前用户信息
    
    需要在 Header 中提供 Authorization: Bearer <token>
    """
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        email=current_user["email"],
        created_at=current_user["created_at"]
    )
