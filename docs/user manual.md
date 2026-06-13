# Hướng Dẫn Sử Dụng Hệ Thống Agent-PM (Tài Khoản Admin)

> Tài liệu hướng dẫn dành cho quản trị viên (admin) hệ thống quản lý dự án **Agent-PM** — nền tảng quản lý dự án tích hợp trợ lý AI qua Gapo.

---

## 1. Truy Cập Hệ Thống

### Link web (cho người dùng bên ngoài)

| Mục đích | Địa chỉ |
|---|---|
| **Web app (truy cập từ Internet)** | http://124.158.15.142:18790 |
| Web app (trong mạng nội bộ LAN) | http://192.168.1.147:8090 |
| Web app (trên máy chạy server) | http://localhost:8090 |

> **Lưu ý:** Router NAT forward cổng WAN `18790` → máy chủ `192.168.1.147:8090` (frontend). Người dùng bên ngoài công ty dùng link đầu tiên. Nếu IP công khai (`124.158.15.142`) thay đổi theo nhà mạng, hãy hỏi quản trị hạ tầng để lấy IP/domain mới.

### Tài khoản Admin mặc định

| Trường | Giá trị |
|---|---|
| **Email** | `admin@bbsw.vn` |
| **Mật khẩu** | `123456` |
| Họ tên | Nguyễn Văn Admin |
| Vai trò | ADMIN |
| Phòng ban / Chức vụ | Ban Giám Đốc / CEO |

> ⚠️ **Bảo mật quan trọng:** Đây là mật khẩu seed mặc định. **Hãy đổi mật khẩu ngay sau lần đăng nhập đầu tiên** (xem mục [6.1](#61-đổi-mật-khẩu)). Toàn bộ tài khoản mẫu trong hệ thống đều dùng chung mật khẩu `123456` — cần đổi trước khi đưa vào sử dụng thực tế.

---

## 2. Đăng Nhập

1. Mở trình duyệt và truy cập link web ở [mục 1](#1-truy-cập-hệ-thống).
2. Tại trang **Đăng nhập** (`/login`), nhập:
   - **Email:** `admin@bbsw.vn`
   - **Mật khẩu:** `123456`
3. Nhấn nút **"Đăng nhập"**.
4. Hệ thống chuyển hướng tới **Dashboard** (trang tổng quan).

Phiên đăng nhập được lưu bằng token JWT trong trình duyệt. Khi token hết hạn, hệ thống sẽ yêu cầu đăng nhập lại.

---

## 3. Tổng Quan Giao Diện

Sau khi đăng nhập, thanh menu bên trái (sidebar) hiển thị các mục chính:

| Menu | Quyền nhìn thấy | Mô tả |
|---|---|---|
| **Dashboard** | Tất cả | Tổng quan dự án, công việc, tiến độ |
| **Dự án (Projects)** | Tất cả | Quản lý danh sách dự án |
| **Công việc (Tasks)** | Tất cả | Quản lý task theo dự án |
| **Worklog** | Tất cả | Ghi nhận giờ công hàng ngày |
| **Cài đặt (Settings)** | **Admin & Manager** | Quản trị hệ thống (xem mục 5) |

> Menu **Cài đặt** chỉ xuất hiện với tài khoản có vai trò **ADMIN** hoặc **MANAGER**. Tài khoản admin có toàn quyền chỉnh sửa trong khu vực này.

---

## 4. Các Vai Trò (Role) Trong Hệ Thống

| Vai trò | Quyền hạn |
|---|---|
| **ADMIN** | Toàn quyền: quản lý người dùng, công ty, mọi dự án |
| **MANAGER** | Quản lý dự án, xem khu vực Cài đặt (hạn chế chỉnh sửa) |
| **MEMBER** | Xem & thao tác Dashboard, Dự án, Công việc, Worklog được giao |
| **VIEWER** | Chỉ đọc toàn bộ |

---

## 5. Khu Vực Cài Đặt Dành Cho Admin (`/settings`)

Khu vực Cài đặt gồm 2 tab chính.

### 5.1. Tab "Thành viên" (Quản lý người dùng) — `/settings/users`

Quản lý toàn bộ tài khoản người dùng trong công ty.

**Các thao tác:**

- **Xem danh sách người dùng:** Hiển thị Họ tên, Email, Vai trò, Trạng thái (Hoạt động/Vô hiệu), trạng thái liên kết Gapo, lần đăng nhập cuối. Hỗ trợ tìm kiếm theo tên/email, lọc theo vai trò và trạng thái, phân trang.

- **Tạo người dùng mới:** Nhấn nút thêm, nhập:
  - Email
  - Họ tên
  - Vai trò (ADMIN / MANAGER / MEMBER / VIEWER)
  - Mật khẩu

  Người dùng mới tự động thuộc công ty của admin.

- **Sửa người dùng:** Cập nhật Họ tên, Vai trò, bật/tắt trạng thái hoạt động, và đặt lại mật khẩu (tùy chọn).

- **Bật/Tắt tài khoản:** Dùng nút biểu tượng để kích hoạt hoặc vô hiệu hóa tài khoản.

  > ⚠️ Admin **không thể tự vô hiệu hóa** tài khoản của chính mình.

**Liên kết tài khoản Gapo cho nhân viên:**

Để nhân viên dùng được chatbot AI qua Gapo, cần liên kết tài khoản hệ thống với tài khoản Gapo:

1. **Xem trạng thái liên kết:** Mỗi nhân viên hiển thị đã liên kết Gapo hay chưa (kèm Gapo User ID, Thread ID, tên Gapo, ngày liên kết).

2. **Cấp mã liên kết:** Nhấn tạo **mã liên kết** (6 ký tự) cho nhân viên. Một cửa sổ hiện ra cho phép sao chép mã hoặc sao chép tin nhắn mẫu để gửi cho nhân viên.
   - Mã có hiệu lực trong **24 giờ**.
   - Nhân viên nhắn `/link {MÃ}` cho bot trên Gapo để hoàn tất liên kết.

3. **Cấp lại mã (relink):** Nếu nhân viên đã liên kết nhưng cần liên kết lại, dùng tùy chọn cấp lại mã.

4. **Hủy liên kết:** Xóa liên kết Gapo của nhân viên (dùng khi nhân viên đổi tài khoản Gapo).

### 5.2. Tab "Công ty" — `/settings/company`

Cấu hình thông tin công ty.

- **Xem thông tin công ty:** Tên công ty, số thành viên, số dự án.
- **Đổi tên công ty:** Chỉnh sửa trực tiếp và lưu.

---

## 6. Các Tác Vụ Quản Trị Thường Gặp

### 6.1. Đổi mật khẩu

Vào trang cá nhân (Profile) để cập nhật mật khẩu của tài khoản admin. **Bắt buộc đổi mật khẩu mặc định `123456` ngay sau lần đăng nhập đầu tiên.**

### 6.2. Onboard nhân viên mới

1. Vào **Cài đặt → Thành viên → Tạo người dùng mới**, cấp email + mật khẩu + vai trò.
2. Cấp **mã liên kết Gapo** và gửi cho nhân viên.
3. Nhân viên đăng nhập web, đồng thời nhắn `/link {MÃ}` cho bot Gapo để dùng chatbot AI.

### 6.3. Xử lý nhân viên nghỉ việc / đổi tài khoản

- Vào **Thành viên**, **vô hiệu hóa** tài khoản (không xóa để giữ lịch sử dữ liệu).
- Nếu đổi tài khoản Gapo: **hủy liên kết Gapo** cũ rồi cấp mã liên kết mới.

---

## 7. Trợ Lý AI Qua Gapo (PM Agent)

Hệ thống tích hợp chatbot AI để nhân viên tương tác qua **Gapo** (nhắn tin tiếng Việt tự nhiên). Các năng lực chính:

- **Hỏi đáp dữ liệu (text2sql):** Trả lời câu hỏi về dự án/công việc bằng truy vấn cơ sở dữ liệu chính xác.
- **Báo cáo (report):** Sinh báo cáo tiến độ, công việc trễ hạn, khối lượng công việc.
- **Lập kế hoạch (planning):** Hỗ trợ lập kế hoạch dự án.
- **Hội thoại (conversation):** Chào hỏi, hướng dẫn.
- **Nhắc nhở (notification):** Tự động nhắc deadline.
- **Cập nhật công việc (task_update):** Xác minh hoàn thành task.
- **Chấm công tự động (check-in):** Nhắc ghi nhận giờ công lúc **11:50** và **17:50** (giờ Việt Nam); nhân viên trả lời để chọn dự án → task → nhập số giờ.

---

## 8. Kiến Trúc Kỹ Thuật (Tham Khảo)

| Thành phần | Công nghệ | Cổng |
|---|---|---|
| Frontend (Web) | React + TypeScript + Vite, Tailwind CSS | host `8090` (WAN `18790`) |
| Backend (API) | FastAPI (Python async) | host `8000` (WAN `3637` — webhook) |
| Cơ sở dữ liệu | PostgreSQL 16 | nội bộ `5432` |
| Cache | Redis 7 | nội bộ `6379` |
| Lưu trữ ảnh | MinIO (S3) | `9000` |
| Proxy LLM | 9router | nội bộ `20128` |

- **API base (frontend gọi):** `/api/v1`
- **Webhook Gapo:** `POST /webhook/gapo` (router NAT WAN `3637` → backend `8000`)
- **Triển khai:** Docker Compose (`docker-compose.yml`)

---

## 9. Lưu Ý Bảo Mật

1. **Đổi ngay** mật khẩu mặc định `123456` của tài khoản admin và mọi tài khoản mẫu.
2. Cổng backend `8000` được phơi ra WAN qua router NAT để nhận webhook Gapo → **phải đặt `GAPO_WEBHOOK_SECRET`** để xác thực chữ ký webhook.
3. Không chia sẻ tài khoản admin; tạo tài khoản riêng theo vai trò cho từng người.
4. Vô hiệu hóa (không xóa) tài khoản nhân viên nghỉ việc để giữ lịch sử dữ liệu.

---

*Tài liệu được tạo cho hệ thống Agent-PM. Cập nhật khi IP công khai, cổng, hoặc tính năng thay đổi.*
