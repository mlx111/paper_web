from langchain_qwq import ChatQwen
import os

from pydantic import SecretStr
from settings.config import config


class QwenModel():
    def __init__(self) -> None:
        self.api_key=config.DASHSCOPE_API_KEY
        self.model_name=config.dashscope_model
        self.BASE_URL=config.DASHSCOPE_API_BASE
        if self.api_key:
            os.environ["DASHSCOPE_API_KEY"] = self.api_key
            os.environ["OPENAI_API_KEY"] = self.api_key
        if self.BASE_URL:
            os.environ["DASHSCOPE_API_BASE"] = self.BASE_URL
        
    def init_model(self,steram:bool):
        model=ChatQwen(
            model=self.model_name,
            api_key=SecretStr(self.api_key),
            base_url=self.BASE_URL,
            temperature=0.7,
            streaming=steram,
        )
        return model

qwen_model=QwenModel()
