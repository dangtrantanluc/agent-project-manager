"""Nền dùng chung cho các luồng "ghi qua chat" (giao việc, thêm thành viên...).

Gom logic LẶP giữa các service: resolve TÊN người/dự án -> bản ghi thật trong
CÙNG company của người gửi, và khung xử lý 3 nhánh kết quả (không thấy / trùng
tên / đúng 1). Trước đây nằm trong TaskCreateService; tách ra để add_member và
mọi luồng ghi sau dùng lại, sửa một chỗ là mọi nơi hưởng.
"""
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Chỉ các vai trò này được thực hiện thao tác ghi cấp dự án qua chat (giống POST /tasks, /members).
PRIVILEGED_ROLES = {"MANAGER", "ADMIN", "SUPER_ADMIN"}
# Mã task có 2 dạng: Jira-style thật của hệ thống ("GAP-T0003", "MTL-T001" — xem
# code_gen) và dạng số trong ngoặc ("[3.2]") đôi khi người dùng gõ. Ưu tiên bắt
# mã Jira-style trước (cụ thể hơn) rồi mới tới dạng số.
_TASK_CODE_JIRA = re.compile(r"\b([A-Z]+\d*-[A-Za-z]\d+)\b", re.IGNORECASE)
_TASK_CODE_NUM = re.compile(r"\[(\d+(?:\.\d+)*)\]")

# Bỏ tiền tố thừa người dùng hay gõ trước tên ("task mẫu mail" -> "mẫu mail")
# để không kéo theo từ rác vào điều kiện khớp tên.
_REF_STOPWORDS = {"task", "công", "việc", "cái", "the"}


def _name_tokens(ref: str) -> list[str]:
    """Tách ref thành các từ có nghĩa (>=2 ký tự, bỏ stopword) để khớp AÐ theo từ.

    Cho phép gõ thiếu/đảo từ ("mẫu mail" khớp "Mẫu Email & WhatsApp") thay vì
    đòi cả chuỗi phải là substring liền mạch.
    """
    toks = re.findall(r"\w+", ref.lower(), flags=re.UNICODE)
    return [t for t in toks if len(t) >= 2 and t not in _REF_STOPWORDS]


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


def _task_row(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "code": row[2],
        "project_id": row[3],
        "assignee_id": row[4],
    }


async def resolve_tasks(db: AsyncSession, ref: str, sender_id: int | None) -> list[dict]:
    """Tìm task theo mã ([3.2]/code) hoặc tên, trong phạm vi quyền người gọi.

    Scope gồm dự án người gọi là owner/account manager/member, hoặc dự án có task
    đang giao cho người gọi. Ưu tiên khớp mã chính xác trước, rồi mới fallback
    tìm gần đúng theo tên các task chưa DONE/CANCELLED.
    """
    ref = (ref or "").strip()
    if not ref or sender_id is None:
        return []

    scope = """
      AND t.project_id IN (
        SELECT p.id FROM projects p WHERE p.owner_id = :s OR p.account_manager_id = :s
        UNION SELECT m.project_id FROM members m WHERE m.user_id = :s
        UNION SELECT t2.project_id FROM tasks t2 WHERE t2.assignee_id = :s
      )
    """

    # Bắt mã: Jira-style ("GAP-T0003") ưu tiên, rồi dạng số trong ngoặc ("[3.2]").
    jira = _TASK_CODE_JIRA.search(ref)
    num = _TASK_CODE_NUM.search(ref)
    code = None
    if jira:
        code = jira.group(1).upper()
    elif num:
        code = num.group(1)
    if code:
        rows = (await db.execute(text(f"""
            SELECT t.id, t.name, t.code, t.project_id, t.assignee_id
            FROM tasks t
            WHERE upper(t.code) = :code {scope}
        """), {"code": code, "s": sender_id})).fetchall()
        if rows:
            return [_task_row(r) for r in rows]

    open_scope = f"{scope}\n          AND t.status::text NOT IN ('DONE', 'CANCELLED')"

    # Khớp theo TỪ: mỗi token của ref phải xuất hiện trong tên (AND nhiều LIKE),
    # nên "mẫu mail" vẫn khớp "Mẫu Email & WhatsApp" dù đảo/thiếu từ. Substring
    # liền mạch cũ là trường hợp con của cái này.
    tokens = _name_tokens(ref)
    if tokens:
        conds = " AND ".join(f"lower(t.name) LIKE :tok{i}" for i in range(len(tokens)))
        params = {f"tok{i}": f"%{tok}%" for i, tok in enumerate(tokens)}
        params["s"] = sender_id
        rows = (await db.execute(text(f"""
            SELECT t.id, t.name, t.code, t.project_id, t.assignee_id
            FROM tasks t
            WHERE {conds} {open_scope}
            ORDER BY t.updated_at DESC
            LIMIT 10
        """), params)).fetchall()
        if rows:
            return [_task_row(r) for r in rows]

    # Fallback mờ: từ-gần-đúng (pg_trgm) bắc cầu viết tắt như "mail" ~ "email".
    # Tắt êm nếu extension chưa cài (giống name_resolver). Ngưỡng 0.3 để không loãng.
    try:
        rows = (await db.execute(text(f"""
            SELECT t.id, t.name, t.code, t.project_id, t.assignee_id,
                   word_similarity(:ref, t.name) AS sim
            FROM tasks t
            WHERE word_similarity(:ref, t.name) > 0.3 {open_scope}
            ORDER BY sim DESC, t.updated_at DESC
            LIMIT 10
        """), {"ref": ref.lower(), "s": sender_id})).fetchall()
        if rows:
            return [_task_row(r) for r in rows]
    except Exception:
        pass  # pg_trgm chưa cài — bỏ qua nhánh mờ, giữ hành vi cũ.

    return []


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
