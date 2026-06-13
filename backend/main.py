import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.core.startup_checks import validate_security_config
from app.modules.admin.router import router as admin_router
from app.modules.agent.router import router as agent_router
from app.modules.agent_audit.router import router as agent_audit_router
from app.modules.auth.router import router as auth_router
from app.modules.backlogs.router import router as backlogs_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.members.router import router as members_router
from app.modules.milestones.router import router as milestones_router
from app.modules.notifications.router import router as notifications_router
from app.modules.projects.router import router as projects_router
from app.modules.scopes.router import router as scopes_router
from app.modules.tags.router import router as tags_router
from app.modules.tasks.router import router as tasks_router
from app.modules.uploads.router import router as uploads_router
from app.modules.users.router import router as users_router
from app.modules.worklogs.router import router as worklogs_router
from ai_agent.checkin.scheduler import start_checkin_scheduler, stop_checkin_scheduler
from core.redis import close_redis
from gapo.gapo_webhook import router as gapo_webhook_router

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s:%(name)s:%(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast in production if security-critical secrets are missing/insecure.
    validate_security_config()
    if os.getenv("CHECKIN_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        start_checkin_scheduler()
    try:
        yield
    finally:
        stop_checkin_scheduler()
        await close_redis()


app = FastAPI(title="BB Project Management API", lifespan=lifespan)

_logger = logging.getLogger("app")


@app.exception_handler(SQLAlchemyError)
async def _sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    # Log đầy đủ phía server, nhưng KHÔNG trả stack trace/SQL ra client.
    _logger.error("DB error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Lỗi hệ thống, vui lòng thử lại sau."})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):
    _logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Lỗi hệ thống, vui lòng thử lại sau."})

origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGIN", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api/v1"
for router in (
    auth_router,
    users_router,
    admin_router,
    dashboard_router,
    projects_router,
    tasks_router,
    tags_router,
    worklogs_router,
    backlogs_router,
    members_router,
    milestones_router,
    scopes_router,
    uploads_router,
    agent_router,
    agent_audit_router,
    notifications_router,
):
    app.include_router(router, prefix=api_prefix)

app.include_router(gapo_webhook_router)

uploads_dir = os.getenv("UPLOAD_DIR", "./uploads/avatars")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads/avatars", StaticFiles(directory=uploads_dir), name="avatars")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get(f"{api_prefix}/health")
async def api_health():
    return {"status": "ok"}
