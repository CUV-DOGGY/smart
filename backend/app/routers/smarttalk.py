from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["外卖智能客服"])

# ==================== Routes ====================
@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """智能客服聊天接口"""
    