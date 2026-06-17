"""Pydantic request models cho project endpoints. Xem chú thích ở tasks/schemas.py."""
from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=300)
    code: str | None = Field(default=None, max_length=16)
    status: str | None = None
    priority: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    description: str | None = Field(default=None, max_length=20000)
    ownerId: int | None = None
    customerName: str | None = Field(default=None, max_length=300)
    accountManagerId: int | None = None
    currencyId: int | None = None


class ProjectUpdateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    code: str | None = Field(default=None, max_length=16)
    status: str | None = None
    priority: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    description: str | None = Field(default=None, max_length=20000)
    ownerId: int | None = None
    customerName: str | None = Field(default=None, max_length=300)
    accountManagerId: int | None = None
    currencyId: int | None = None
    gapoThreadId: str | None = None
