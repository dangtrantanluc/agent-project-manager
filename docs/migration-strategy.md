# Chiến lược Migration DB — đánh giá & đề xuất

> Trạng thái: **ĐỀ XUẤT, chưa áp dụng.** Tài liệu này đánh giá rủi ro của cơ chế
> migration hiện tại và đề xuất phương án. Việc đổi quy trình deploy cần người
> vận hành duyệt trước khi thực thi.

## 1. Hiện trạng

Schema DB được nạp qua `docker-entrypoint-initdb.d/`:

```
init/init.sql                -> 001-init.sql        (schema gốc + tables)
init/seed.sql                -> 002-seed.sql        (dữ liệu demo)
init/agent_role.sql          -> 003-agent-role.sql
init/notifications.sql       -> 004-notifications.sql
init/gapo_link_codes.sql     -> 005-gapo-link-codes.sql
init/agent_features.sql      -> 006-agent-features.sql   (progress col + risk_alerts)
init/tags.sql                -> 007-tags.sql
init/deadline_quickactions.sql -> 008-deadline-quickactions.sql (snooze_reminder_until)
```

**Đặc điểm quan trọng:** `docker-entrypoint-initdb.d/` chỉ chạy **MỘT LẦN, khi data
volume còn TRỐNG** (lần đầu khởi tạo container Postgres). Sau khi DB đã có dữ liệu,
mọi file thêm/sửa trong `init/` **KHÔNG tự động được apply**.

Codebase truy vấn bằng **raw SQL** (`sqlalchemy.text()`), **không có ORM models**
(`backend/app/models` không tồn tại).

## 2. Rủi ro

| # | Rủi ro | Mức độ |
|---|--------|--------|
| 1 | Thêm cột/bảng vào `init/*.sql` trên môi trường đã chạy → **không áp dụng**; phải `ALTER` thủ công, dễ quên → lệch schema giữa dev và prod | Cao |
| 2 | Không có bảng theo dõi phiên bản schema → không biết DB đang ở "version" nào | Trung bình |
| 3 | Không có cơ chế rollback chuẩn | Trung bình |
| 4 | Quy ước hiện tại đã idempotent một phần (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`) nhưng KHÔNG được tự chạy lại → tính idempotent không phát huy | Thấp |

Thực tế đã xảy ra: cột `snooze_reminder_until` (008) phải apply thủ công bằng
`ALTER TABLE` trên container đang chạy, song song với việc đăng ký vào compose.

## 3. Phương án

### Phương án A — Alembic (chuẩn ngành)
- **Ưu:** versioning + upgrade/downgrade chuẩn, cộng đồng lớn.
- **Nhược với dự án này:** vì dùng raw SQL không có ORM models, **autogenerate
  không hoạt động** → phải viết mọi migration bằng tay (`op.execute("ALTER ...")`).
  Lợi ích so với phương án B giảm đáng kể, nhưng thêm 1 dependency + learning curve.
- Nếu chọn: `alembic init`, cấu hình `sqlalchemy.url` từ env, baseline = stamp
  schema hiện tại là revision đầu, mỗi thay đổi sau = 1 revision viết tay.

### Phương án B — Bảng tracking + script số thứ tự (NHẸ, khuyến nghị trước mắt)
Giữ nguyên `init/*.sql` cho lần khởi tạo trống, **bổ sung** một runner idempotent
cho môi trường đã có dữ liệu:

1. Tạo bảng `schema_migrations(version text primary key, applied_at timestamptz default now())`.
2. Đặt các thay đổi tăng dần trong `migrations/009_*.sql`, `010_*.sql`, ...
   (mỗi file idempotent: `ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`).
3. Script khởi động backend (hoặc lệnh `make migrate`) duyệt các file chưa có trong
   `schema_migrations`, chạy trong transaction, rồi ghi version.

- **Ưu:** không thêm dependency nặng, khớp với phong cách raw-SQL hiện tại, áp dụng
  được trên cả DB trống lẫn DB đã chạy, có tracking + idempotent thật.
- **Nhược:** tự viết runner (~50 dòng), không có downgrade tự động (viết tay nếu cần).

## 4. Khuyến nghị

- **Ngắn hạn (nội bộ, 1 công ty):** Phương án B. Rủi ro thấp, đủ giải quyết vấn đề
  "sửa schema trên DB đang chạy không tự apply". Có thể thêm dần.
- **Khi quy mô/đội ngũ lớn hơn hoặc chuyển sang ORM:** cân nhắc Phương án A (Alembic).
- **Tuyệt đối nên có ngay:** quy ước "mọi thay đổi schema = 1 file migration mới
  trong `migrations/` (idempotent) + ghi `schema_migrations`", và lệnh chạy migration
  tách khỏi bước nạp `initdb.d`.

## 5. Việc cần làm nếu duyệt Phương án B (để tham khảo, CHƯA làm)
- [ ] Thêm `migrations/000_baseline.sql` đánh dấu schema hiện tại.
- [ ] Viết runner (Python, dùng asyncpg/SQLAlchemy sẵn có) đọc `migrations/*.sql`,
      so với `schema_migrations`, chạy phần còn thiếu trong transaction.
- [ ] Gắn runner vào entrypoint backend (chạy trước `uvicorn`) hoặc lệnh thủ công.
- [ ] Di chuyển các thay đổi tương lai khỏi việc sửa trực tiếp `init/*.sql` cũ.
