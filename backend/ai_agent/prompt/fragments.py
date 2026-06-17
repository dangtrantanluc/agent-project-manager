"""Các mảnh chỉ thị (prompt fragments) dùng chung cho nhiều agent.

Trước đây các câu "Chỉ SELECT/WITH", "Không markdown", "kết thúc bằng ;"... bị
copy-paste ở text2sql, report, planning. Gom về một nguồn để sửa một chỗ áp mọi
agent và tránh lệch wording.
"""

# Chỉ thị an toàn SQL: chỉ truy vấn đọc.
SELECT_ONLY = (
    "Chỉ tạo câu truy vấn SELECT hoặc WITH. TUYỆT ĐỐI không INSERT/UPDATE/DELETE/"
    "DROP/ALTER/TRUNCATE/CREATE/REPLACE/MERGE/GRANT/REVOKE/VACUUM/CALL/DO."
)

# Mỗi câu SQL phải kết thúc bằng dấu chấm phẩy.
SQL_END_SEMICOLON = "Mỗi câu SQL PHẢI kết thúc bằng dấu chấm phẩy (;)."

# Định dạng output: không markdown, không giải thích.
NO_MARKDOWN = "Không dùng markdown."
NO_EXPLANATION = "Không giải thích."

# Quy tắc ngày tháng theo PostgreSQL (dùng cho text2sql/report).
DATE_RULES_PG = (
    "Dùng cú pháp ngày của PostgreSQL: CURRENT_DATE, NOW(), date_trunc(...), "
    "NOW() - INTERVAL '7 days'. KHÔNG hard-code ngày cụ thể."
)


def sql_rules_block() -> str:
    """Khối quy tắc SQL chung, mỗi quy tắc một dòng gạch đầu dòng."""
    return "\n".join(
        f"- {r}" for r in (SELECT_ONLY, SQL_END_SEMICOLON, NO_MARKDOWN, NO_EXPLANATION)
    )
