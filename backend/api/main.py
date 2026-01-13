"""
FastAPI 主应用
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .chat import router as chat_router
from .auth import router as auth_router
from .middleware import RequestContextMiddleware
from backend.core.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("=" * 50)
    logger.info("FAgent Backend 服务启动中...")
    logger.info(f"日志目录: logs/backend/")
    logger.info("服务已就绪")
    logger.info("=" * 50)
    
    yield
    
    # 关闭时
    logger.info("FAgent Backend 服务关闭中...")
    logger.info("服务已关闭")


app = FastAPI(
    title="FAgent API",
    description="智能股票交易助手 API",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置中间件（注意顺序：先添加的后执行）
# 1. 请求上下文中间件
app.add_middleware(RequestContextMiddleware)

# 2. CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router)
app.include_router(auth_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "FAgent API",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

