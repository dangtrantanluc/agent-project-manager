import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv()


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        if explicit.startswith("postgresql://"):
            return explicit.replace("postgresql://", "postgresql+asyncpg://", 1)
        return explicit

    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "agent_pm")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


engine = create_async_engine(
    _database_url(),
    pool_pre_ping=True,
    # Pool đủ lớn cho tải đồng thời; mặc định SQLAlchemy (5+10) sẽ cạn ở ~1k user.
    pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "30")),
    # Tái tạo connection sau 30' để tránh connection chết (firewall/idle timeout).
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    # Fail nhanh khi pool cạn thay vì treo request vô hạn.
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
    # asyncpg: timeout khi mở connection + timeout cứng mỗi câu lệnh.
    connect_args={"timeout": 10, "command_timeout": 30},
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
