"""Startup security validation.

Fails fast in production when security-critical secrets are missing or left at
their insecure development defaults. In non-production it only logs loud
warnings so local dev keeps working without a full secret setup.
"""
import logging
import os

logger = logging.getLogger(__name__)

_INSECURE_JWT_DEFAULT = "dev-secret-change-me"


def _is_production() -> bool:
    return os.getenv("APP_ENV", os.getenv("ENV", "development")).lower() in {
        "prod",
        "production",
    }


def validate_security_config() -> None:
    """Raise RuntimeError in production if critical secrets are unsafe."""
    problems: list[str] = []

    jwt_secret = os.getenv("JWT_SECRET", "")
    if not jwt_secret or jwt_secret == _INSECURE_JWT_DEFAULT:
        problems.append(
            "JWT_SECRET chưa được đặt (hoặc còn để mặc định 'dev-secret-change-me'). "
            "Token có thể bị giả mạo."
        )

    agent_token = os.getenv("AGENT_API_TOKEN", "")
    if not agent_token:
        problems.append(
            "AGENT_API_TOKEN chưa được đặt. Các endpoint service-to-service sẽ không an toàn."
        )

    gapo_secret = os.getenv("GAPO_WEBHOOK_SECRET", "")
    if not gapo_secret:
        problems.append(
            "GAPO_WEBHOOK_SECRET chưa được đặt. Webhook Gapo sẽ chấp nhận payload không ký."
        )

    if not problems:
        return

    if _is_production():
        joined = "\n  - ".join(problems)
        raise RuntimeError(
            "Cấu hình bảo mật không hợp lệ cho production:\n  - " + joined
        )

    for p in problems:
        logger.warning("[startup] CẢNH BÁO BẢO MẬT (dev): %s", p)
