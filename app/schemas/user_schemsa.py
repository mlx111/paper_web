
from pydantic import BaseModel,EmailStr,Field,model_validator
from typing import Annotated


#用户名和密码的限制 ...表示必须填写

UsernameStr=Annotated[str,Field(...,min_length=4,max_length=20,description="用户名")]
RawPasswordStr=Annotated[str,Field(...,min_length=6,max_length=20,description="密码")]

class RegisterIn(BaseModel):
    email:EmailStr
    username:UsernameStr
    password:RawPasswordStr
    confirm_password:RawPasswordStr
    code:Annotated[str,Field(...,min_length=6,max_length=6,description="验证码")]
    
    @model_validator(mode="after")
    def passwords_is_macth(self)-> "RegisterIn":
        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self 
    

class UserSchema(BaseModel):
    username:UsernameStr
    email:EmailStr
    password:RawPasswordStr
        