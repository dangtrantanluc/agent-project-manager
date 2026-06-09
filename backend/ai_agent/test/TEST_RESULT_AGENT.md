# Báo cáo kiểm thử — Hệ thống AI Agent (bb-pm)

| | |
|---|---|
| **Phạm vi** | `backend/ai_agent/` — Text-to-SQL, Intent Router, Memory, Report, Notification |
| **Loại test** | Unit + component, mock toàn bộ LLM/DB/Redis (offline, không tốn token) |
| **Người thực hiện** | QA (senior, domain agent) |
| **Ngày chạy** | 2026-06-07 |
| **Môi trường** | container `backend`, Python 3.12.13, pytest 9.0.3 |
| **Commit gốc** | `74eaa604` |
| **Lệnh chạy** | `docker exec backend python -m pytest ai_agent/test/ -v` |

---

## 1. Tóm tắt điều hành

| Chỉ số | Baseline (trước) | Sau khi sửa + bổ sung |
|---|---|---|
| Tổng test | 46 | **109** |
| Pass | 27 | **109** |
| Fail | **19** | **0** |
| Error | 0 | 0 |
| Thời gian | ~5.4s | ~4.5s |

**Kết luận:** Sau khi xử lý, **109/109 test PASS**. 19 fail ở baseline **KHÔNG phải bug sản phẩm** mà là **test lỗi thời** (regression ở tầng test) — chi tiết mục 4. Các guardrail bảo mật cốt lõi của agent (chống SQL injection, chống rò rỉ dữ liệu, phân quyền theo user) đã được kiểm chứng và **hoạt động đúng**.

---

## 2. Phân rã kết quả theo file

| File test | Số test | Kết quả | Trọng tâm |
|---|---:|:---:|---|
| `test_text2sql.py` | 21 | ✅ PASS | Sinh SQL hợp lệ, schema single-company, bind `:user_id` |
| `test_text2sql_security.py` *(mới)* | 41 | ✅ PASS | Guardrail bảo mật: DML/DDL, multi-statement, comment-bypass, hàm/cột cấm, phân quyền, injection `user_id` |
| `test_router_fallback.py` *(mới)* | 22 | ✅ PASS | Định tuyến tất định: `_pick_agent`, fallback từ khoá, parser JSON chịu lỗi |
| `test_memory.py` | 5 | ✅ PASS | Load/save memory, rolling summary mỗi 4 lượt, company_id |
| `test_memory_integration.py` | 2 | ✅ PASS | Router nạp memory, Gapo dùng thread_id làm conversation_id |
| `test_report_agent.py` | 2 | ✅ PASS | Lập kế hoạch báo cáo, từ chối SQL không an toàn |
| `test_report_templates.py` | 6 | ✅ PASS | Registry template báo cáo |
| `test_deadline_notifications.py` | 10 | ✅ PASS | Sinh thông báo nhắc deadline |
| **Tổng** | **109** | **✅ 0 fail** | |

---

## 3. Thiết kế test — Catalog test case mới (63 case)

Cách tiếp cận **risk-based + adversarial**: ưu tiên bề mặt tấn công cao nhất của
agent là Text-to-SQL (prompt injection → SQL độc hại → rò rỉ/phá dữ liệu). Mỗi
lớp phòng thủ được test cả case hợp lệ (phải cho qua) lẫn case tấn công (phải chặn).

### 3.1 Bảo mật Text-to-SQL — `test_text2sql_security.py` (41 case)

**L1 — `is_safe_sql()` (lọc tĩnh):**

| Nhóm | Case | Kỳ vọng |
|---|---|---|
| Hợp lệ | `simple_select`, `cte_with`, `select_uppercase` | ✅ chấp nhận |
| DML/DDL | `drop_table`, `delete_rows`, `update_rows`, `insert_rows`, `truncate`, `grant` | ❌ chặn |
| Injection | `multi_statement` (`SELECT 1; DROP…`), `named_placeholder` (`:task_id` chưa bind) | ❌ chặn |
| Hợp lệ hoá | `no_semicolon`, `not_select` (EXPLAIN) | ❌ chặn |
| Rò rỉ/nguy hiểm | `password_hash`, `information_schema`, `pg_catalog`, `pg_sleep_dos`, `pg_read_file`, `dblink_exfil` | ❌ chặn |
| Né tránh | `comment_hides_drop`, `block_comment_mutation` (comment che mutation/`;`) | ❌ chặn |

**L2 — Phân quyền (`generate_sql` + restriction):**

| Case | Kỳ vọng |
|---|---|
| MEMBER/VIEWER/`""`/None/`guest` **không có** user_id | ❌ raise `Restricted user without id` |
| MEMBER có id nhưng LLM trả SQL toàn cục | ❌ raise `Restricted query not scoped to current user` |
| MEMBER có id + SQL đã lọc theo id | ✅ cho qua |
| ADMIN/MANAGER (hoa & thường) truy vấn toàn cục | ✅ cho qua |
| LLM bị dụ trả `DROP` / `password_hash` (prompt injection) | ❌ raise `Unsafe SQL generated` |

**L3 — Bind & ép kiểu `user_id`:**

| Case | Kỳ vọng |
|---|---|
| `:user_id` với id=7 | thay thành `7`, không còn placeholder |
| id độc: `"7; DROP TABLE users"`, `"1 OR 1=1"`, `"abc"`, `0`, `-1` | ép về None → MEMBER bị từ chối an toàn |
| `_coerce_user_id` đơn vị | chỉ nhận int dương; còn lại → None |

### 3.2 Định tuyến intent — `test_router_fallback.py` (22 case)

| Nhóm | Case tiêu biểu | Kỳ vọng |
|---|---|---|
| `_pick_agent` | rỗng / list Agent / list string / name rỗng | default `conversation`, lấy confidence cao nhất |
| Fallback từ khoá | "lập kế hoạch"→planning, "báo cáo"→report, "thông báo"→notification, "bao nhiêu dự án"→text2sql (10 case) | đúng agent |
| Fallback không kích hoạt | router đã chắc chắn (conf>0), hoặc agent≠conversation | giữ nguyên |
| Ưu tiên | "lập kế hoạch chia task" (planning vs data) | planning thắng |
| Parser JSON chịu lỗi | JSON sạch / trong ```fence``` / lẫn text / rác hoàn toàn | không crash; rác → điểm 0 |

---

## 4. Phát hiện chính (Findings)

### 🟡 FINDING-1 — 19 test lỗi thời (regression tầng test, KHÔNG phải bug sản phẩm)

- **Hiện tượng:** `test_text2sql.py` có 19 test fail ở baseline.
- **Nguyên nhân gốc:** `Text2SQLAgent.generate_sql()` đã được **siết bảo mật**: mặc
  định coi caller là user bị giới hạn (không phải ADMIN/MANAGER). Khi gọi không
  truyền `user_role`, agent raise `ValueError("Restricted user without id cannot
  run data queries")` **trước khi** sinh SQL. Test cũ gọi `generate_sql(question)`
  không truyền role/id → rơi vào nhánh từ chối, lệch với assertion cũ.
- **Đánh giá:** Hành vi sản phẩm **đúng và an toàn hơn** (mặc định deny). Lỗi nằm
  ở test chưa cập nhật theo security contract mới.
- **Xử lý:** Cập nhật test truyền `user_role="ADMIN"` cho các case truy vấn toàn
  cục (đúng ngữ nghĩa "câu hỏi cấp hệ thống"). Sau sửa: 21/21 pass.
- **Bài học:** Rule bảo mật mới ("restricted user must scope", "deny khi thiếu id")
  được thêm vào code nhưng **chưa có test bảo vệ** → đã bổ sung ở `test_text2sql_security.py`.

### 🟢 FINDING-2 — Guardrail bảo mật hoạt động đúng (đã kiểm chứng)

41 test tấn công (DML, multi-statement, comment-bypass, đọc file, DoS `pg_sleep`,
rò rỉ `password_hash`, injection qua `user_id`) đều bị chặn đúng. Phòng thủ nhiều
lớp (is_safe_sql + restriction + backstop "SQL phải chứa id user") vững.

### 🟢 FINDING-3 — Router fallback & parser chịu lỗi tốt

Khi LLM router thiếu chắc chắn hoặc trả output bẩn, hệ thống không crash và phục
hồi intent hợp lý bằng từ khoá tiếng Việt. 22/22 pass.

---

## 5. Khoảng trống & rủi ro còn lại (Gaps)

| # | Khoảng trống | Rủi ro | Khuyến nghị |
|---|---|---|---|
| G1 | **Không có test tích hợp end-to-end** với DB/LLM thật (toàn mock) | Trung bình | Thêm 1 bộ smoke test gắn nhãn `@pytest.mark.integration` chạy với Postgres + LLM thật trong CI nightly |
| G2 | `PMMultiAgentRouter` **hard-code** `gemini-2.5-flash` thay vì đọc `ROUTER_MODEL_NAME` | Thấp | Sửa code đọc env; thêm test config |
| G3 | Chưa test **độ chính xác phân loại intent của LLM** (chỉ test fallback tất định) | Trung bình | Xây bộ eval dataset (câu hỏi → intent đúng), đo accuracy, chạy định kỳ (tốn token → tách khỏi unit) |
| G4 | Chưa có **conftest.py / pytest.ini** | Thấp | Thêm `pytest.ini` (marker `integration`, lọc warning) để chuẩn hoá |
| G5 | `text2sql.execute()` (pipeline đầy đủ + cache Redis) chưa có test | Trung bình | Mock Redis, test cache hit/miss, skip-cache cho câu hỏi thời gian tương đối |
| G6 | Memory summary phụ thuộc `gpt-4o-mini` mặc định khác model chính | Thấp | Thống nhất qua env, test fallback khi LLM tóm tắt lỗi (đã có 1 test) |

---

## 6. Artifact

- `results_junit.xml` — kết quả máy đọc (JUnit), sinh bởi `--junitxml`.
- File test mới: `test_text2sql_security.py`, `test_router_fallback.py`.
- File test sửa: `test_text2sql.py` (cập nhật theo security contract).

## 7. Cách tái lập

```bash
# Toàn bộ suite agent
docker exec backend python -m pytest ai_agent/test/ -v

# Chỉ bộ bảo mật
docker exec backend python -m pytest ai_agent/test/test_text2sql_security.py -v

# Sinh lại JUnit XML
docker exec backend python -m pytest ai_agent/test/ \
  --junitxml=/app/ai_agent/test/results_junit.xml
```

Tất cả test **không cần DB/Redis/LLM thật** (mock hết) → chạy offline, không tốn token.
