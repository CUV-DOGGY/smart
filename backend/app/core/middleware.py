from fastapi.middleware.cors import CORSMiddleware
# ==================== Middleware ====================
def setup_middleware(app: FastAPI):
    """配置中间件"""
    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )