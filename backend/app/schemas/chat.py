from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    #用户id
   user_id : str = Field(min_length=1)
   #会话id
   session_id : str = Field(min_length=1)
   #用户消息
   message : str = Field(min_length=1, max_length=1000)


class ChatResponse(BaseModel):
   #机器人回复
   response : str 
   #会话id
   session_id : str 