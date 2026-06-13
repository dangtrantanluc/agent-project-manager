# Tài Liệu Đặc Tả Yêu Cầu (Requirement) — Hệ Thống Agent-PM

> **Ghi chú phiên bản:** Tài liệu đã đối chiếu với sơ đồ luồng PM 4 giai đoạn (Giao việc → Nhắc việc → Cập nhật tiến độ → Rủi ro & báo cáo). Các mục đánh dấu **MỚI — chưa implement** (FR-17, FR-18) là yêu cầu phát sinh từ sơ đồ, hiện chưa có trong code. BR-5 đã được sửa để hỗ trợ luồng cập nhật task qua hội thoại (sơ đồ bước 13–14).

---

## A. TỔNG QUAN

### A.1. Mô tả sản phẩm

**Agent-PM** là hệ thống **quản lý dự án (Project Management)** dành cho doanh nghiệp, tích hợp **trợ lý AI (PM-Bot)** hỗ trợ nhân viên tương tác bằng **tiếng Việt tự nhiên** qua nền tảng chat **Gapo**. Hệ thống phục vụ quản lý vòng đời dự án — từ lập kế hoạch, phân chia công việc, theo dõi tiến độ, đến chấm công (worklog) — đồng thời tự động hóa nhắc nhở và thu thập báo cáo công việc qua chatbot.

### A.2. Đối tượng người dùng

| Vai trò | Mô tả |
|---|---|
| **ADMIN** | Quản trị viên công ty: quản lý người dùng, công ty, toàn bộ dự án |
| **MANAGER** | Quản lý dự án: tạo/sửa dự án, công việc, thành viên |
| **MEMBER** | Nhân viên: thực hiện công việc được giao, ghi nhận giờ công |
| **VIEWER** | Chỉ đọc (read-only) |


## B. YÊU CẦU CHỨC NĂNG (FUNCTIONAL REQUIREMENTS)

### FR-1. Xác thực & Phân quyền

- **FR-1.1** Người dùng đăng nhập bằng **email + mật khẩu**; hệ thống cấp **JWT token** chứa `user_id, email, role`.
- **FR-1.2** Đăng ký (self-register) **bị vô hiệu hóa** — chỉ ADMIN tạo tài khoản.
- **FR-1.3** Ghi nhận thời điểm đăng nhập gần nhất (`last_login_at`).
- **FR-1.4** Tài khoản bị vô hiệu hóa (`active = false`) không thể đăng nhập / gọi API.
- **FR-1.5** Phân quyền 2 lớp:
  - **Theo vai trò:** ADMIN/MANAGER có quyền đầy đủ; MEMBER/VIEWER bị giới hạn.
  - **Theo dữ liệu dự án:** MEMBER/VIEWER chỉ xem được dự án mà họ là owner, account manager, thành viên, hoặc có task/worklog/backlog trong đó.
- **FR-1.6** Xác thực service-to-service cho AI Agent qua header `X-Agent-Token`.

### FR-2. Quản lý người dùng (Admin)

- **FR-2.1** ADMIN xem danh sách người dùng công ty (tìm kiếm theo tên/email, lọc theo vai trò & trạng thái, phân trang).
- **FR-2.2** Tạo người dùng mới (email duy nhất, họ tên, vai trò, mật khẩu — mật khẩu được hash).
- **FR-2.3** Cập nhật người dùng (họ tên, vai trò, bật/tắt hoạt động, đặt lại mật khẩu).
- **FR-2.4** ADMIN **không thể tự vô hiệu hóa** tài khoản của chính mình.

### FR-3. Quản lý dự án (Project)

- **FR-3.1** Liệt kê dự án (lọc theo trạng thái, độ ưu tiên, tìm kiếm; phân trang; có phân quyền theo membership).
- **FR-3.2** Tạo / sửa / xóa dự án. Thuộc tính: tên, mã (duy nhất), trạng thái, ưu tiên, ngày bắt đầu/kết thúc, mô tả, khách hàng, owner, account manager, tiền tệ, ước lượng giờ.
- **FR-3.3** Chuyển trạng thái dự án theo luồng: **PLANNED → PENDING → IN_PROGRESS → DONE** (hoặc CANCELLED).
- **FR-3.4** Xem chi tiết dự án với các tab: Tổng quan, Công việc, Milestones, Worklogs, Scope, Thành viên.
- **FR-3.5** Báo cáo dự án: digest (tóm tắt), weekly-report (báo cáo tuần) cho từng dự án và toàn bộ.
- **FR-3.6** **Import công việc từ Excel**: chế độ thường (mapping cột) và chế độ **AI** (LLM phân tích file → đề xuất cấu trúc milestone + task). Mỗi import có bước **preview** trước khi **confirm**.
- **FR-3.7** Giao diện dự án hỗ trợ **Kanban (kéo-thả)** và **bảng (table)**.

### FR-4. Quản lý công việc (Task)

- **FR-4.1** Liệt kê task (lọc theo dự án, trạng thái, người được giao, milestone, tìm kiếm; sắp xếp theo deadline/cập nhật).
- **FR-4.2** Tạo / sửa / xóa task. Thuộc tính: tên, trạng thái, ưu tiên, deadline, mô tả, kết quả, vấn đề, người được giao, milestone.
- **FR-4.3** Chuyển trạng thái task: **TODO → IN_PROGRESS → DONE** (hoặc CANCELLED).
- **FR-4.4** MANAGER/ADMIN sửa mọi task; MEMBER/VIEWER chỉ sửa task được giao cho mình.
- **FR-4.5** Quản lý **blocker** (chướng ngại) của task với mức độ: LOW / MED / HIGH / CRITICAL.
- **FR-4.6** Các truy vấn hỗ trợ: task quá hạn (overdue), task tồn đọng lâu (stale), kiểm tra chất lượng dữ liệu, gợi ý task từ backlog, truy vấn xem task quá hạn đó có liên quan đến task trước không (ví dụ như user A phải làm task X để user mới làm được task Y).
- **FR-4.7** Tự động đi push người khác khi manager hỏi (ví dụ trường hợp manager hỏi task quá hạn và bắt con PM đó đi nhắn tin với người đó để push)
- **FR-4.8** Giao diện task hỗ trợ **Kanban (kéo-thả)** và **danh sách**.

### FR-5. Milestone (Mốc dự án)

- **FR-5.1** Liệt kê / tạo / sửa / xóa milestone trong dự án (yêu cầu MANAGER/ADMIN để tạo).
- **FR-5.2** Mỗi milestone theo dõi: ngày đến hạn, số task, số task hoàn thành, % hoàn thành.

### FR-6. Scope (Phạm vi công việc)

- **FR-6.1** Liệt kê / tạo / sửa / xóa scope trong dự án (sắp theo thứ tự `sequence`, hỗ trợ kéo-thả sắp xếp lại).
- **FR-6.2** Thuộc tính scope: tên, ghi chú, ước lượng giờ, gán task/người phụ trách.

### FR-7. Thành viên dự án (Member)

- **FR-7.1** Liệt kê / thêm / sửa / xóa thành viên của dự án (yêu cầu MANAGER/ADMIN).

### FR-8. Ghi nhận giờ công (Worklog)

- **FR-8.1** Liệt kê worklog (lọc theo dự án, task, người dùng, khoảng ngày; chế độ "của tôi").
- **FR-8.2** Tạo / sửa / xóa worklog (bắt buộc: ngày công, số giờ, dự án).
- **FR-8.3** MEMBER/VIEWER chỉ xem worklog của mình hoặc thuộc dự án họ tham gia.
- **FR-8.4** Tổng giờ công được tổng hợp lên task và dự án.

### FR-9. Backlog (Chấm công chờ duyệt)

- **FR-9.1** Tạo backlog ghi nhận giờ công ở trạng thái **PENDING** (nguồn: manual / checkin / import).
- **FR-9.2** Duyệt (**APPROVED**) → cộng vào tổng giờ; từ chối (**REJECTED**) kèm lý do; đặt lại (reset) về PENDING.
- **FR-9.3** MANAGER/ADMIN tạo backlog cho người khác; các vai trò khác chỉ tạo cho chính mình.

### FR-10. Dashboard (Tổng quan)

- **FR-10.1** Hiển thị tổng quan: số dự án (tổng/đang chạy/hoàn thành/tạm dừng), tiến độ tổng hợp (biểu đồ), timeline sự kiện sắp tới.
- **FR-10.2** Bộ lọc: dự án, trạng thái dự án, người phụ trách, khoảng thời gian (7/30/90 ngày).
- **FR-10.3** Cung cấp KPI và dữ liệu biểu đồ.

### FR-11. Thông báo (Notification)

- **FR-11.1** Thông báo in-app: chuông + badge đếm số chưa đọc (tự cập nhật mỗi 30 giây), trang danh sách đầy đủ.
- **FR-11.2** Lọc theo "tất cả / chưa đọc"; đánh dấu đã đọc từng cái hoặc tất cả; click điều hướng theo `link`.

### FR-12. Hồ sơ cá nhân (Profile)

- **FR-12.1** Cập nhật họ tên, ngôn ngữ (Việt/Anh), timezone.
- **FR-12.2** Upload **ảnh đại diện** (PNG/JPEG/WEBP/GIF, tối đa 2MB; lưu MinIO hoặc đĩa).

### FR-13. Trợ lý AI (PM-Bot qua Gapo)

- **FR-13.1** Nhận tin nhắn từ Gapo qua **webhook** (`POST /webhook/gapo`), xác thực chữ ký HMAC-SHA256 (`GAPO_WEBHOOK_SECRET`).
- **FR-13.2** **Liên kết tài khoản Gapo:** ADMIN cấp **mã liên kết 6 ký tự** (hết hạn 24 giờ); nhân viên nhắn `/link {MÃ}` cho bot để liên kết tài khoản hệ thống ↔ Gapo. Hỗ trợ cấp lại (relink) và hủy liên kết.
- **FR-13.3** **Định tuyến đa agent (multi-agent router):** LLM phân loại ý định tin nhắn ra **danh sách agent**, chạy song song rồi gộp kết quả. Có fallback theo từ khóa khi LLM không chắc chắn.
- **FR-13.4** Các agent chuyên biệt:
  - **text2sql** — Trả lời câu hỏi dữ liệu bằng cách sinh & thực thi truy vấn SQL chỉ-đọc (SELECT), kèm nhiều lớp an toàn chống injection. Diễn giải kết quả thành câu tiếng Việt.
  - **report** — Sinh báo cáo (tiến độ dự án, theo kỳ, quá hạn/sắp tới, khối lượng theo người) bằng **template SQL viết sẵn**, fallback LLM tự sinh khi không khớp template.
  - **planning** — Lập kế hoạch dự án có cấu trúc (tối đa 3 milestone, mỗi milestone ≤ 2 task) qua structured output.
  - **conversation** — Chào hỏi, trợ giúp; có fast-path không gọi LLM cho câu phổ biến.
  - **notification** — Sinh nội dung nhắc deadline; **luôn có template tất định** dự phòng khi LLM lỗi.
  - **task_update** — Khi user **chủ động yêu cầu cập nhật** task qua hội thoại (ví dụ trả lời tin nhắc deadline "đã xong 80%", hoặc nhắn "tôi update task X của dự án Y sang DONE"), agent bóc tách ý định (task nào, trạng thái/% mới) → **xác minh quyền & danh tính** (assignee khớp, task tồn tại) → **tự cập nhật `tasks.status`/tiến độ + ghi `agent_audit_log`** → xác nhận lại ngắn gọn với user; đánh dấu follow-up = REPLIED. Agent **chỉ ghi khi user nêu rõ ý định trong hội thoại**, không tự suy diễn từ tin nhắn mơ hồ.
    - **FR-13.4a (Đề xuất khi mơ hồ):** Nếu không xác định được task/giá trị mới (nhiều task pending, không rõ %), agent **hỏi lại / đề xuất** thay vì ghi bừa; chỉ ghi sau khi user xác nhận.
- **FR-13.5** **Bộ nhớ hội thoại:** lưu mỗi lượt vào `agent_memory`; nạp tối đa **5 lượt gần nhất** + bản tóm tắt; tự **tóm tắt mỗi 4 lượt** bằng LLM.

### FR-17. Giao việc & thông báo qua Gapo *(MỚI — chưa implement)*

> Phản ánh Giai đoạn 1 của sơ đồ luồng (PM → AI-PM Core → GapoWork → Thành viên). Hiện chưa có trong code; ghi nhận là yêu cầu cần phát triển.

- **FR-17.1** Khi MANAGER/ADMIN **tạo task** (hoặc materialize kế hoạch do AI sinh thành task), hệ thống **tự soạn và gửi tin giao việc** qua Gapo tới người được giao, gồm: tên task, dự án, deadline, mô tả ngắn.
- **FR-17.2** Đích gửi: **DM trực tiếp tới assignee** (qua `gapo_user_maps`) là bắt buộc; gửi vào **thread/group dự án** là tùy chọn khi project có cấu hình thread Gapo.
- **FR-17.3** Cần định nghĩa ánh xạ **project → thread/group Gapo** (cấu hình `gapo_thread_id` ở cấp dự án) để hỗ trợ FR-17.2; nếu chưa cấu hình thì chỉ gửi DM assignee.
- **FR-17.4** Tin giao việc **tự gửi** (không cần PM duyệt), có **template tất định dự phòng** khi LLM lỗi (xem NFR-REL-1). Chống gửi trùng bằng `correlation_id` theo `task_id`.
- **FR-17.5** Assignee chưa liên kết Gapo (`gapo_user_maps` rỗng) thì bỏ qua gửi DM, ghi log; vẫn tạo notification in-app (FR-11).

### FR-18. Phát hiện rủi ro & cảnh báo có duyệt *(MỚI — chưa implement)*

> Phản ánh Giai đoạn 4 của sơ đồ luồng (Rủi ro & báo cáo). Hiện chưa có job phát hiện at-risk; ghi nhận là yêu cầu cần phát triển.

- **FR-18.1** Job định kỳ **quét rủi ro dự án/task**: quá hạn (overdue), tồn đọng lâu không cập nhật (stale), blocker chưa giải quyết (severity HIGH/CRITICAL), và phụ thuộc chéo (task A trễ chặn task B — xem FR-4.6).
- **FR-18.2** Với mỗi rủi ro, agent **soạn nội dung cảnh báo + đề xuất hành động** (ví dụ: nhắc/push người liên quan — xem FR-4.7).
- **FR-18.3** **Human-in-the-loop bắt buộc:** cảnh báo rủi ro và đề xuất hành động **phải gửi PM chờ xác nhận** trước khi thực thi (gửi tin push, đổi trạng thái...). PM có thể duyệt / sửa / bỏ qua.
  - Đây là điểm khác biệt với FR-15 (nhắc deadline thường) — **nhắc deadline tự gửi thẳng tới member, không cần duyệt**; còn cảnh báo rủi ro **luôn cần PM duyệt**.
- **FR-18.4** Lưu vết toàn bộ chu trình cảnh báo (phát hiện → đề xuất → quyết định của PM → hành động) vào `agent_audit_log`.

### FR-14. Chấm công tự động (Check-in qua Gapo)

- **FR-14.1** Bộ lập lịch gửi tin nhắn check-in 2 lần/ngày (Thứ Hai–Sáu): **trưa 11:50** và **cuối ngày 17:50** (giờ VN).
- **FR-14.2** **Máy trạng thái hội thoại (FSM):** Chọn dự án → chọn task → nhập nội dung & số giờ → xác nhận → (tùy chọn) thêm worklog khác.
- **FR-14.3** Hỗ trợ nhập bằng **nút bấm**, **gõ số thứ tự**, hoặc **gõ tên** (tìm kiếm); hỗ trợ "hủy"/"bỏ qua".
- **FR-14.4** **LLM bóc tách** số giờ + mô tả từ câu tự do; nếu mơ hồ thì hỏi lại (tối đa 3 lần); validate 0 < giờ ≤ 24; chống ghi trùng (idempotency).
- **FR-14.5** Nhắc nhở người chưa check-in (trưa 12:30, chiều 18:30); báo cáo người thiếu check-in cho admin (19:00).

### FR-15. Nhắc deadline tự động

- **FR-15.1** Gửi nhắc task sắp đến hạn (trong ~2 ngày) và đến hạn hôm nay — 2 lần/ngày (mặc định **9:00** và **14:00**, cấu hình được).
- **FR-15.2** Dùng `correlation_id` để chống gửi trùng lặp.

### FR-16. Đa ngôn ngữ

- **FR-16.1** Giao diện hỗ trợ **Tiếng Việt (mặc định)** và **English**; người dùng đổi ngôn ngữ ở trang Profile.

---

## C. RÀNG BUỘC NGHIỆP VỤ (BUSINESS RULES)

- **BR-1** Email người dùng và mã (code) công ty/dự án là **duy nhất**.
- **BR-2** Worklog: `0 < giờ ≤ 24`.
- **BR-3** Mã liên kết Gapo dài **6 ký tự**, hết hạn sau **24 giờ**.
- **BR-4** Kế hoạch do AI sinh: tối đa **3 milestone**, mỗi milestone tối đa **2 task**, mô tả ngắn gọn.
- **BR-5** Agent `task_update` **được phép cập nhật** `tasks.status`/tiến độ **chỉ khi** user **chủ động yêu cầu rõ ràng trong hội thoại** (nêu đúng task + trạng thái/% mới) **và** danh tính/quyền khớp (assignee hoặc MANAGER/ADMIN). Mọi cập nhật phải ghi `agent_audit_log`. Khi tin nhắn mơ hồ, agent **hỏi lại / đề xuất**, **không tự suy diễn để ghi**. *(Thay thế quy tắc cũ "chỉ xác minh, không tự đổi".)*
- **BR-5a** **Ranh giới tự-gửi vs cần-duyệt:** Nhắc deadline & check-in & tin giao việc (FR-15, FR-14, FR-17) **tự gửi** tới member không cần duyệt. Cảnh báo rủi ro at-risk & đề xuất hành động chủ động (FR-18, FR-4.7) **bắt buộc PM xác nhận** trước khi gửi/thực thi.
- **BR-6** Truy vấn SQL của agent chỉ được **SELECT/WITH**, chặn mọi lệnh ghi & truy cập cột nhạy cảm (`password_hash`, `pg_*`, `information_schema`...), giới hạn thời gian thực thi 5 giây.
- **BR-7** Bộ lập lịch dùng **PostgreSQL advisory lock** để tránh chạy trùng job khi nhiều instance.
- **BR-8** Lịch check-in & nhắc nhở chỉ chạy **Thứ Hai–Thứ Sáu** (giờ Asia/Ho_Chi_Minh).
- **BR-9** Tạo mã task và mã project, tạo tag cho task để quản lý công việc
- **BR-10** Cho phép người dùng update trực tiếp status task (qua UI) và điền worklog hàng ngày; ngoài ra có thể cập nhật status task **qua hội thoại với agent** (xem BR-5).

---

## D. YÊU CẦU PHI CHỨC NĂNG (NON-FUNCTIONAL)

### D.1. Bảo mật
- **NFR-SEC-1** Mật khẩu lưu dưới dạng **hash bcrypt**; không lưu plaintext.
- **NFR-SEC-2** Xác thực qua **JWT**; mọi endpoint nghiệp vụ yêu cầu token hợp lệ.
- **NFR-SEC-3** Webhook Gapo xác thực **chữ ký HMAC-SHA256**.
- **NFR-SEC-4** AI Agent dùng tài khoản DB **read-only riêng** cho truy vấn dữ liệu.
- **NFR-SEC-5** Chống SQL injection nhiều lớp ở agent text2sql/report.

### D.2. Hiệu năng
- **NFR-PERF-1** Truy vấn DB qua **asyncpg connection pool** (min 2, max 10); statement timeout 5s.
- **NFR-PERF-2** Cache kết quả sinh SQL trong **Redis** (TTL ~1 giờ), bỏ cache cho câu hỏi thời gian tương đối.
- **NFR-PERF-3** Agent router nạp song song (intent + memory + profile) để giảm độ trễ.
- **NFR-PERF-4** Frontend dùng React Query cache (staleTime 30s), optimistic update cho kéo-thả.

### D.3. Độ tin cậy
- **NFR-REL-1** Thông báo/nhắc nhở theo lịch luôn có **template tất định dự phòng** khi LLM lỗi.
- **NFR-REL-2** Chống gửi trùng bằng `correlation_id`; chống ghi worklog trùng (idempotency).
- **NFR-REL-3** Agent router fail-fast (timeout ngắn) để tầng trên fallback.

### D.4. Khả năng vận hành
- **NFR-OPS-1** Triển khai bằng **Docker Compose** (db, redis, backend, frontend, minio, 9router).
- **NFR-OPS-2** Bộ lập lịch bật/tắt qua biến `CHECKIN_SCHEDULER_ENABLED`.

---

