from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class KotakLogin(BaseModel):
    consumer_key: SecretStr = Field(min_length=1, max_length=2048)
    ucc: str = Field(min_length=1, max_length=30, pattern=r'^[A-Za-z0-9]+$')
    mobile: str = Field(pattern=r'^\+[0-9]{10,15}$')
    totp: SecretStr
    mpin: SecretStr

    @field_validator('ucc', 'mobile', mode='before')
    @classmethod
    def clean_identity(cls,value):
        return value.strip() if isinstance(value,str) else value

    @field_validator('totp','mpin')
    @classmethod
    def six_digits(cls,value):
        text=value.get_secret_value()
        if len(text)!=6 or not text.isascii() or not text.isdigit():
            raise ValueError('Enter six digits.')
        return value
