"""Nền dùng chung cho các luồng "ghi qua chat" (giao việc, thêm thành viên...).

Gom logic LẶP giữa các service: resolve TÊN người/dự án -> bản ghi thật trong
CÙNG company của người gửi, và khung xử lý 3 nhánh kết quả (không thấy / trùng
tên / đúng 1). Trước đây nằm trong TaskCreateService; tách ra để add_member và
mọi luồng ghi sau dùng lại, sửa một chỗ là mọi nơi hưởng.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Chỉ các vai trò này được thực hiện thao tác ghi cấp dự án qua chat (giống POST /tasks, /members).
PRIVILEGED_ROLES = {"MANAGER", "ADMIN", "SUPER_ADMIN"}


def is_privileged(role: str | None) -> bool:
    return str(role or "").upper() in PRIVILEGED_ROLES


async def resolve_users(db: AsyncSession, name: str, sender_id: int) -> list[dict]:
    """Tìm user theo tên (full_name hoặc gapo_full_name) trong cùng company người gửi."""
    like = f"%{name.lower()}%"
    rows = (await db.execute(text("""
        SELECT u.id, u.full_name
        FROM users u
        WHERE u.active = true
          AND u.company_id = (SELECT company_id FROM users WHERE id = :sender)
          AND (lower(u.full_name) LIKE :like
               OR lower(COALESCE((SELECT gapo_full_name FROM gapo_user_maps WHERE user_id = u.id), '')) LIKE :like)
        ORDER BY u.full_name
    """), {"sender": sender_id, "like": like})).fetchall()
    return [{"user_id": r[0], "full_name": r[1]} for r in rows]


async def resolve_projects(db: AsyncSession, name: str, sender_id: int) -> list[dict]:
    """Tìm dự án theo tên trong cùng company; ưu tiên dự án đang chạy."""
    like = f"%{name.lower()}%"
    rows = (await db.execute(text("""
        SELECT p.id, p.name, p.company_id
        FROM projects p
        WHERE p.company_id = (SELECT company_id FROM users WHERE id = :sender)
          AND lower(p.name) LIKE :like
        ORDER BY (p.status::text IN ('PLANNED','IN_PROGRESS')) DESC, p.name
    """), {"sender": sender_id, "like": like})).fetchall()
    return [{"id": r[0], "name": r[1], "company_id": r[2]} for r in rows]


def resolve_one(
    items: list[dict],
    raw_name: str,
    kind: str,
    label_key: str,
) -> tuple[dict | None, str | None]:
    """Chọn đúng 1 bản ghi từ kết quả resolve, hoặc trả câu hỏi-lại.

    Gói khung 3 nhánh mà mọi luồng ghi đều lặp:
      - 0 kết quả  -> (None, "không tìm thấy ...")
      - >1 kết quả -> (None, "trùng tên ..., nói rõ giúp")  -> KHÔNG tự đoán
      - 1 kết quả  -> (item, None)

    kind: danh từ tiếng Việt ("người", "dự án"). label_key: key chứa tên hiển thị.
    """
    if not items:
        return None, (f"Mình chưa tìm thấy {kind} \"{raw_name}\" trong hệ thống. "
                      "Bạn kiểm tra lại giúp mình nhé.")
    if len(items) > 1:
        names = ", ".join(str(it.get(label_key, "")) for it in items)
        return None, (f"Có nhiều {kind} khớp \"{raw_name}\": {names}. "
                      "Bạn nói rõ giúp mình là cái nào nhé.")
    return items[0], None
