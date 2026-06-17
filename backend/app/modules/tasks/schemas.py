"""Pydantic request models cho task endpoints.

Trước đây router nhận `body: dict` → không validate kiểu, field sai lọt xuống SQL
(type confusion). Các model này validate ở BIÊN rồi `.model_dump()` về dict để
phần thân hàm cũ (truy cập body[...]) giữ nguyên.

extra="ignore": bỏ qua field lạ (giữ tương thích với client cũ), KHÔNG forbid để
tránh chặn nhầm request hợp lệ. Giá trị chính là validate kiểu + độ dài.
"""
from pydantic import BaseModel, ConfigDict, Field


class TaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=500)
    projectId: int | None = None
    status: str | None = None
    priority: str | None = None
    deadline: str | None = None
    endAt: str | None = None
    assigneeId: int | None = None
    milestoneId: int | None = None
    currencyId: int | None = None
    description: str | None = Field(default=None, max_length=20000)


class TaskUpdateIn(BaseModel):
    # exclude_unset khi dump để giữ ngữ nghĩa PATCH (chỉ cập nhật field được gửi).
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=500)
    status: str | None = None
    priority: str | None = None
    deadline: str | None = None
    endAt: str | None = None
    result: str | None = None
    issues: str | None = None
    assigneeId: int | None = None
    milestoneId: int | None = None
    currencyId: int | None = None
    description: str | None = Field(default=None, max_length=20000)
