"""Điểm DUY NHẤT để dựng LLM client.

Trước đây 16 nơi tự gọi ChatOpenAI(...) với cấu hình lệch nhau (timeout 10/15/20/
25/30/60, retry 0/1/2). Gom về đây để:
  - Sửa model/timeout/endpoint một chỗ thay vì 16 chỗ.
  - Gắn nhãn `purpose` vào metadata → sau này cắm callback đo token/cost một chỗ.
  - Thống nhất việc đọc biến môi trường (kể cả biến *_ROUTER cho intent router).

Hành vi cũ được giữ nguyên: mỗi call site truyền đúng timeout/temperature/
reasoning_effort như trước.
"""
import os

from langchain_openai import ChatOpenAI

# Sentinel: phân biệt "không truyền reasoning_effort" với "truyền None".
_UNSET = object()


def _resolve(model, api_key, base_url, router: bool):
    """Điền model/api_key/base_url từ env nếu chưa truyền. router=True ưu tiên biến *_ROUTER."""
    if router:
        model = model or os.getenv("MODEL_NAME_ROUTER") or os.getenv("MODEL_NAME")
        api_key = api_key or os.getenv("API_KEY_ROUTER") or os.getenv("API_KEY")
        base_url = base_url or os.getenv("BASE_URL_ROUTER") or os.getenv("BASE_URL")
    else:
        model = model or os.getenv("MODEL_NAME")
        api_key = api_key or os.getenv("API_KEY")
        base_url = base_url or os.getenv("BASE_URL")
    return model, api_key, base_url


def make_llm(
    *,
    purpose: str,
    timeout: int = 30,
    max_retries: int = 1,
    temperature=None,
    reasoning_effort=_UNSET,
    router: bool = False,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> ChatOpenAI:
    """Dựng ChatOpenAI. `purpose` là nhãn để log/đo cost (vd 'text2sql','router')."""
    model, api_key, base_url = _resolve(model, api_key, base_url, router)
    kwargs = dict(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        metadata={"purpose": purpose},
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning_effort is not _UNSET:
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatOpenAI(**kwargs)


def make_async_openai(*, purpose: str, router: bool = False):
    """Dựng AsyncOpenAI thuần (dùng cho memory summarization). Trả về client SDK gốc."""
    from openai import AsyncOpenAI

    _, api_key, base_url = _resolve(None, None, None, router)
    return AsyncOpenAI(api_key=api_key, base_url=base_url)
