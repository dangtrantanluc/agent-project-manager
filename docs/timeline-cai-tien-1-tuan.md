# Timeline Cải Tiến Agent-PM — Nhồi Toàn Bộ Trong 1 Tuần

> **Phạm vi:** Gom **tất cả các cải tiến** mà requirement yêu cầu so với code hiện tại — gồm phần **chưa làm** (FR-17, FR-18, FR-4.6, FR-4.7, FR-13.4a) và phần **cần tinh chỉnh theo sơ đồ** (BR-5/task_update, FR-15). Tương ứng hoàn thiện **sơ đồ luồng PM 4 giai đoạn**: Giao việc → Nhắc việc → Cập nhật tiến độ → Rủi ro & báo cáo.
>
> **Tuần:** Thứ Hai 2026-06-15 → Thứ Sáu 2026-06-19 (demo). Buffer cuối tuần dự phòng.
>
> ⚠️ **Cảnh báo độ căng:** Nhồi đủ chừng này trong 5 ngày là **rất căng**. File này sắp xếp theo mức ưu tiên P0 → P2; nếu trễ, cắt theo thứ tự ngược (bỏ P2 trước). Phần "Cắt giảm nếu trễ" ở cuối nêu rõ đường lùi.

---

## 0. Hiện trạng (đã đối chiếu code)

| Hạng mục | Trạng thái | Vị trí |
|---|---|---|
| Router đa agent + 6 agent | ✅ Có | `ai_agent/router/message_router.py` |
| Check-in + nhắc deadline 9:00/14:00 | ✅ Có | `ai_agent/checkin/scheduler.py` |
| `task_update` (cập nhật qua hội thoại) | ✅ Có; cần tinh chỉnh FR-13.4a | `ai_agent/task_update/task_verify_service.py` |
| Thông báo in-app | ✅ Có | `ai_agent/notification/inapp_repository.py` |
| Gửi tin Gapo (DM/thread) | ✅ Có client | `gapo/gapo_client.py::send_message` |
| `agent_audit_log` | ✅ Có | nhiều nơi |
| **FR-17** tự gửi tin giao việc khi tạo task | ❌ **CHƯA** | `tasks/router.py::create_task` không gọi Gapo |
| **FR-18** job quét rủi ro + duyệt PM | ❌ **CHƯA** | scheduler không có job risk |
| **FR-4.6** phụ thuộc chéo (A trễ chặn B) | ❌ **CHƯA** | chưa có quan hệ dependency |
| **FR-4.7** tự push người liên quan (có duyệt) | ❌ **CHƯA** | gắn với FR-18 |
| **FR-13.4a** đề xuất khi mơ hồ | ⚠️ Một phần | có "hỏi lại"; chưa đề xuất lựa chọn |

**Ranh giới BR-5a (không được làm sai):** FR-17 / FR-14 / FR-15 → **tự gửi** thẳng tới member. FR-18 / FR-4.7 → **bắt buộc PM duyệt** trước khi thực thi.

---

## Lịch nén 5 ngày

```
T2 (15/6) │ P0 FR-17 Giao việc Gapo: service + template + chống trùng
          │ P1 FR-13.4a tinh chỉnh task_update (đề xuất khi mơ hồ)
T3 (16/6) │ P0 FR-17 wiring create_task + materialize plan + thread dự án
          │ P2 FR-4.6 phụ thuộc chéo (heuristic + cột dependency tối thiểu)
T4 (17/6) │ P0 FR-18 risk_scanner + bảng risk_alerts + đăng ký job
          │ P1 FR-18.2 sinh đề xuất hành động (+template tất định)
T5 (18/6) │ P0 FR-18 hàng đợi duyệt PM (approve/edit/dismiss) + thực thi
          │ P1 FR-4.7 push người liên quan đi qua duyệt + UI cảnh báo
T6 (19/6) │ Test đầu-cuối 4 giai đoạn + tài liệu + env + DEMO
```

---

## Thứ Hai 15/6 — FR-17 hạ tầng giao việc + FR-13.4a

**P0 — FR-17 (Giai đoạn 1):**
- [ ] Migration: thêm `gapo_thread_id` cấp dự án (NULL → chỉ DM).
- [ ] Service `ai_agent/assignment/assignment_notifier.py`: `notify_task_assigned(task, assignee, project)` — resolve `gapo_user_maps`, soạn **template tất định** (tên task/dự án/deadline/mô tả), gửi `gapo_client.send_message`.
- [ ] Chống trùng `correlation_id = task_assign:{task_id}` (tái dùng pattern deadline).
- [ ] Fallback assignee chưa liên kết → bỏ DM, ghi log, tạo notification in-app (FR-11, FR-17.5).
- [ ] Unit test: có map / không map / gửi trùng.

**P1 — FR-13.4a (tinh chỉnh task_update):**
- [ ] Khi mơ hồ (nhiều task pending / không rõ %) → trả về **danh sách đề xuất lựa chọn** thay vì chỉ "hỏi lại"; chỉ ghi sau khi user xác nhận. Sửa `task_verify_service.py` (dòng ~234).
- [ ] Test case: tin nhắn mơ hồ → agent đề xuất, không tự ghi.

---

## Thứ Ba 16/6 — FR-17 wiring + FR-4.6

**P0 — FR-17 wiring:**
- [ ] Gắn `notify_task_assigned` vào `tasks/router.py::create_task` (~dòng 163, background).
- [ ] Gắn vào materialize kế hoạch AI → mỗi task có assignee đều phát tin.
- [ ] FR-17.2: nếu `project.gapo_thread_id` có → gửi thêm tin vào thread; NULL → chỉ DM.
- [ ] Audit mỗi lần gửi; integration test tạo task → DM + audit + không trùng.
- [ ] UI: ô nhập `gapo_thread_id` ở trang dự án (Manager/Admin).

**P2 — FR-4.6 phụ thuộc chéo (làm tối thiểu, làm trước vì FR-18 cần):**
- [ ] Thêm quan hệ dependency tối thiểu: cột/bảng `task_dependencies(task_id, blocks_task_id)` + API gán.
- [ ] Truy vấn "task A trễ → chặn task B": nếu chưa kịp bảng đầy đủ, dùng **heuristic** (cùng milestone/scope, thứ tự sequence) và **ghi log giới hạn** (no silent cap).

---

## Thứ Tư 17/6 — FR-18 quét rủi ro + đề xuất

**P0 — FR-18 scanner (Giai đoạn 4):**
- [ ] Service `ai_agent/risk/risk_scanner.py`: quét **overdue / stale / blocker HIGH-CRITICAL / phụ thuộc chéo (FR-4.6)**. Tái dùng truy vấn overdue/stale trong `report_templates.py`.
- [ ] Bảng `risk_alerts(id, project_id, task_id, risk_type, severity, suggestion_text, target_user, status[PENDING/APPROVED/EDITED/DISMISSED/EXECUTED], correlation_id, created_at)`.
- [ ] Đăng ký job vào `scheduler.py`: advisory lock (BR-7), chỉ T2–T6 (BR-8), giờ qua env `RISK_SCAN_HOUR`.
- [ ] Audit giai đoạn "phát hiện" (FR-18.4).

**P1 — FR-18.2 sinh đề xuất:**
- [ ] Mỗi rủi ro → `{nội dung cảnh báo, hành động đề xuất}` (vd push assignee). **Template tất định** khi LLM lỗi (NFR-REL-1).
- [ ] Unit test mỗi loại rủi ro → sinh alert PENDING (chưa gửi gì).

---

## Thứ Năm 18/6 — FR-18 duyệt PM + FR-4.7

**P0 — Human-in-the-loop (BR-5a):**
- [ ] API `app/modules/risk/router.py`: `GET /risk-alerts` (PENDING), `POST /{id}/approve` (thực thi: push Gapo / đổi trạng thái → EXECUTED), `POST /{id}/edit`, `POST /{id}/dismiss`.
- [ ] Thực thi dùng `gapo_client.send_message`; chống trùng `correlation_id`; ghi audit "quyết định PM → hành động" (hoàn tất 4 mốc FR-18.4).
- [ ] Notification in-app cho PM khi có alert mới.

**P1 — FR-4.7 + UI:**
- [ ] Hành động "push người liên quan" đi qua **đúng hàng đợi duyệt** (không tự gửi).
- [ ] UI tab "Cảnh báo rủi ro" (Manager/Admin): thẻ cảnh báo + nút Duyệt/Sửa/Bỏ qua + badge PENDING.
- [ ] Integration test: scan → alert → approve → push gửi + audit đủ 4 mốc.

---

## Thứ Sáu 19/6 — Tích hợp 4 giai đoạn + Demo

- [ ] **Test đầu-cuối theo sơ đồ:**
  1. PM tạo task → member nhận DM giao việc (FR-17).
  2. Tới hạn → nhắc deadline tự gửi (FR-15, đã có).
  3. Member trả "đã xong 80%" → `task_update` ghi tiến độ; nếu mơ hồ → đề xuất (FR-13.4a).
  4. Job risk phát hiện overdue/phụ thuộc chéo → alert PENDING → PM duyệt → push (FR-18, FR-4.7).
- [ ] Khẳng định ranh giới BR-5a bằng test (FR-17 tự gửi, FR-18 chờ duyệt).
- [ ] Full suite `ai_agent/test` xanh (hiện 46 passed) + test mới.
- [ ] Cập nhật `docs/user manual.md` mục 7; thêm env `RISK_SCAN_ENABLED`, `RISK_SCAN_HOUR` vào `docker-compose.yml`.
- [ ] **DEMO** 4 giai đoạn cho team.

---

## Cắt giảm nếu trễ (đường lùi theo ưu tiên)

| Nếu trễ ngày... | Cắt |
|---|---|
| T3 | FR-4.6 chỉ làm **heuristic**, hoãn bảng `task_dependencies` đầy đủ sang tuần sau |
| T4–T5 | FR-18 chỉ quét **overdue + blocker** (bỏ phụ thuộc chéo khỏi scanner tuần này) |
| T5 | UI cảnh báo dùng tạm danh sách đơn giản; nút Sửa (edit) hoãn, giữ Duyệt/Bỏ qua |
| Bí cuối tuần | Giữ **P0** (FR-17 + FR-18 lõi); đẩy FR-13.4a, FR-4.7 UI sang tuần sau |

**Tuyệt đối không cắt:** chống trùng `correlation_id`, template tất định dự phòng (NFR-REL-1), ranh giới tự-gửi vs chờ-duyệt (BR-5a), ghi `agent_audit_log`.

## Định nghĩa Hoàn Thành (DoD)

- FR-17: tạo task → assignee đã liên kết nhận DM đúng, không trùng, có audit; chưa liên kết → notification in-app.
- FR-18: job sinh alert PENDING; PM duyệt/sửa/bỏ qua; chỉ sau duyệt mới gửi; chu trình đủ trong `agent_audit_log`.
- FR-13.4a: tin mơ hồ → agent đề xuất, không tự ghi.
- BR-5a có test khẳng định; tài liệu + env + docker-compose cập nhật; full test xanh.
