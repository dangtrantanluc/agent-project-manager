from pydantic import BaseModel
from typing import Optional


class RegisterRequest(BaseModel):
    email: str
    password: str
    fullName: str
    companyName: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserDTO(BaseModel):
    id: int
    email: str
    fullName: str
    avatarUrl: Optional[str] = None
    role: str
    companyName: Optional[str] = None
    lang: str
    timezone: str
    isSuperAdmin: bool


class AuthResponse(BaseModel):
    user: UserDTO
    accessToken: str
