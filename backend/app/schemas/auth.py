from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserLoginJSON(BaseModel):
    email: EmailStr
    password: str


class TokenPayload(BaseModel):
    sub: int


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=72)

    @field_validator('password')
    @classmethod
    def bcrypt_length(cls,value):
        if len(value.encode('utf-8')) > 72:
            raise ValueError('Password must not exceed 72 UTF-8 bytes')
        return value
