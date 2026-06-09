-- =============================================================
--  MOCK SEED DATA — BB-PM
--  Công ty: BBSW Software
--  Password mặc định tất cả user: 123456
--  Schema (init.sql) chỉ tạo cấu trúc; toàn bộ data (kể cả lookup
--    currencies & task_status) nằm ở file này.
--  Tiền tệ trên projects/tasks tham chiếu currencies qua currency_id.
-- =============================================================

-- ─── CURRENCIES (lookup) ─────────────────────────────────────
INSERT INTO currencies (code, symbol, rate) VALUES
  ('VND', '₫', 1.0),
  ('USD', '$', 25000.0),
  ('EUR', '€', 27000.0)
ON CONFLICT (code) DO NOTHING;

-- ─── TASK STATUS (lookup UI: todo/in_progress/done/cancelled) ─
INSERT INTO task_status (code, label, color, sort_order) VALUES
  ('todo',        'Todo',        '#94a3b8', 1),
  ('in_progress', 'In Progress', '#3b82f6', 2),
  ('done',        'Done',        '#22c55e', 3),
  ('cancelled',   'Cancelled',   '#ef4444', 4)
ON CONFLICT (code) DO NOTHING;

-- ─── COMPANIES ────────────────────────────────────────────────
INSERT INTO companies (id, name, code, updated_at)
VALUES (1, 'BBSW Software', 'BBSW', NOW())
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    code = EXCLUDED.code,
    updated_at = NOW();

SELECT setval(pg_get_serial_sequence('companies', 'id'), GREATEST((SELECT MAX(id) FROM companies), 1));

-- ─── USERS ───────────────────────────────────────────────────
-- password: 123456  →  $2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S
INSERT INTO users (email, password_hash, full_name, role, department, position, is_admin, updated_at) VALUES
  ('admin@bbsw.vn',      '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Nguyễn Văn Admin',  'ADMIN',   'Ban Giám Đốc',  'CEO',                true,  NOW()),
  ('lan.pm@bbsw.vn',     '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Trần Thị Lan',      'MANAGER', 'Quản lý Dự án', 'Project Manager',    false, NOW()),
  ('hung.pm@bbsw.vn',    '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Lê Văn Hùng',       'MANAGER', 'Quản lý Dự án', 'Project Manager',    false, NOW()),
  ('minh.dev@bbsw.vn',   '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Phạm Minh Tuấn',    'MEMBER',  'Kỹ thuật',      'Backend Developer',  false, NOW()),
  ('linh.dev@bbsw.vn',   '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Ngô Thị Linh',      'MEMBER',  'Kỹ thuật',      'Frontend Developer', false, NOW()),
  ('duc.dev@bbsw.vn',    '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Vũ Đức Anh',        'MEMBER',  'Kỹ thuật',      'Fullstack Developer',false, NOW()),
  ('hoa.qa@bbsw.vn',     '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Đinh Thị Hoa',      'MEMBER',  'Kiểm thử',      'QA Engineer',        false, NOW()),
  ('tung.ba@bbsw.vn',    '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Hoàng Minh Tùng',   'MEMBER',  'Phân tích',     'Business Analyst',   false, NOW()),
  ('son.devops@bbsw.vn', '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Bùi Thanh Sơn',     'MEMBER',  'Hạ tầng',       'DevOps Engineer',    false, NOW()),
  ('luc@bbsw.vn',        '$2b$10$a1aOazHbNVhGEXBVU6zXHe.zI0wvuJF9vM4uS5BA1UUZP3v8rfD9S', 'Đặng Trần Tấn Lực', 'MEMBER',  'Kỹ thuật',      'Developer',          false, NOW())
ON CONFLICT (email) DO NOTHING;

-- ─── PROJECTS ────────────────────────────────────────────────
-- tiền tệ & khách hàng inline trực tiếp
INSERT INTO projects (
  name, code, status, priority,
  start_date, end_date, description,
  total_hours,
  task_count, member_count, worklog_count, milestone_count,
  currency_id,
  customer_name,
  owner_id, account_manager_id,
  updated_at
) VALUES
  (
    'CRM Thaco Go-Live Phase 1', 'THACO-CRM-P1',
    'IN_PROGRESS', 'HIGH',
    '2026-01-15', '2026-06-30',
    'Triển khai hệ thống CRM cho THACO Group — giai đoạn 1 bao gồm quản lý khách hàng, cơ hội bán hàng và báo cáo.',
    0,
    0, 0, 0, 0,
    (SELECT id FROM currencies WHERE code='VND'),
    'THACO Group',
    (SELECT id FROM users WHERE email='lan.pm@bbsw.vn'),
    (SELECT id FROM users WHERE email='lan.pm@bbsw.vn'),
    NOW()
  ),
  (
    'MTL Odoo 19 Migration', 'MTL-ODOO19',
    'IN_PROGRESS', 'URGENT',
    '2026-03-01', '2026-08-31',
    'Nâng cấp hệ thống Odoo từ v16 lên v19 cho MTL Việt Nam, bao gồm migration dữ liệu và custom module.',
    0,
    0, 0, 0, 0,
    (SELECT id FROM currencies WHERE code='VND'),
    'MTL Việt Nam',
    (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
    (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
    NOW()
  ),
  (
    'BB-PM Internal Tool', 'BBPM-INTERNAL',
    'IN_PROGRESS', 'HIGH',
    '2026-04-01', '2026-09-30',
    'Xây dựng công cụ quản lý dự án nội bộ tích hợp AI Agent để tự động hóa báo cáo và theo dõi tiến độ.',
    0,
    0, 0, 0, 0,
    (SELECT id FROM currencies WHERE code='VND'),
    NULL,
    (SELECT id FROM users WHERE email='admin@bbsw.vn'),
    (SELECT id FROM users WHERE email='lan.pm@bbsw.vn'),
    NOW()
  ),
  (
    'Vingroup Data Platform', 'VGDP-2026',
    'PLANNED', 'MEDIUM',
    '2026-07-01', '2026-12-31',
    'Xây dựng nền tảng dữ liệu tập trung cho Vingroup — data lake, ETL pipeline và dashboard BI.',
    0,
    0, 0, 0, 0,
    (SELECT id FROM currencies WHERE code='VND'),
    'Vingroup JSC',
    (SELECT id FROM users WHERE email='lan.pm@bbsw.vn'),
    (SELECT id FROM users WHERE email='lan.pm@bbsw.vn'),
    NOW()
  ),
  (
    'Mobile App THACO Phase 2', 'THACO-MOB-P2',
    'DONE', 'MEDIUM',
    '2025-09-01', '2026-03-31',
    'Ứng dụng mobile quản lý đại lý và giám sát KPI cho hệ thống phân phối THACO.',
    0,
    0, 0, 0, 0,
    (SELECT id FROM currencies WHERE code='VND'),
    'THACO Group',
    (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
    (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
    NOW()
  ),
  (
    'Phần mềm Quản lý Logistics MTL', 'MTL-LOGISTICS',
    'PLANNED', 'HIGH',
    '2026-04-06', '2026-09-30',
    'Triển khai phần mềm Quản lý Logistics cho MTL Logistics trên nền Odoo 19 (BBSW). 4 giai đoạn / 26 tuần: Sales & CS, Operations & Hải quan, Báo cáo & Tự động hóa, Kế toán & VAS TT200. Mục tiêu: 100% quy trình MTL Logistics số hóa trên Odoo 19.',
    0,
    0, 0, 0, 0,
    (SELECT id FROM currencies WHERE code='VND'),
    'MTL Logistics',
    (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
    (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
    NOW()
  );

-- ─── MEMBERS ─────────────────────────────────────────────────
INSERT INTO members (project_id, user_id, role, updated_at)
SELECT p.id, u.id, r.role, NOW()
FROM (SELECT id FROM projects WHERE code='THACO-CRM-P1') p
CROSS JOIN (VALUES
  ('lan.pm@bbsw.vn',   'Project Manager'),
  ('minh.dev@bbsw.vn', 'Backend Developer'),
  ('linh.dev@bbsw.vn', 'Frontend Developer'),
  ('hoa.qa@bbsw.vn',   'QA Engineer'),
  ('tung.ba@bbsw.vn',  'Business Analyst')
) AS r(email, role)
JOIN users u ON u.email = r.email
ON CONFLICT (project_id, user_id) DO NOTHING;

INSERT INTO members (project_id, user_id, role, updated_at)
SELECT p.id, u.id, r.role, NOW()
FROM (SELECT id FROM projects WHERE code='MTL-ODOO19') p
CROSS JOIN (VALUES
  ('hung.pm@bbsw.vn',  'Project Manager'),
  ('duc.dev@bbsw.vn',  'Odoo Developer'),
  ('minh.dev@bbsw.vn', 'Backend Developer'),
  ('tung.ba@bbsw.vn',  'Business Analyst'),
  ('hoa.qa@bbsw.vn',   'QA Engineer')
) AS r(email, role)
JOIN users u ON u.email = r.email
ON CONFLICT (project_id, user_id) DO NOTHING;

INSERT INTO members (project_id, user_id, role, updated_at)
SELECT p.id, u.id, r.role, NOW()
FROM (SELECT id FROM projects WHERE code='BBPM-INTERNAL') p
CROSS JOIN (VALUES
  ('admin@bbsw.vn',      'Product Owner'),
  ('lan.pm@bbsw.vn',     'Project Manager'),
  ('minh.dev@bbsw.vn',   'Backend Developer'),
  ('linh.dev@bbsw.vn',   'Frontend Developer'),
  ('duc.dev@bbsw.vn',    'Fullstack Developer'),
  ('son.devops@bbsw.vn', 'DevOps'),
  ('hoa.qa@bbsw.vn',     'QA Engineer')
) AS r(email, role)
JOIN users u ON u.email = r.email
ON CONFLICT (project_id, user_id) DO NOTHING;

INSERT INTO members (project_id, user_id, role, updated_at)
SELECT p.id, u.id, r.role, NOW()
FROM (SELECT id FROM projects WHERE code='VGDP-2026') p
CROSS JOIN (VALUES
  ('lan.pm@bbsw.vn',  'Project Manager'),
  ('hung.pm@bbsw.vn', 'Technical Lead'),
  ('tung.ba@bbsw.vn', 'Business Analyst')
) AS r(email, role)
JOIN users u ON u.email = r.email
ON CONFLICT (project_id, user_id) DO NOTHING;

INSERT INTO members (project_id, user_id, role, updated_at)
SELECT p.id, u.id, r.role, NOW()
FROM (SELECT id FROM projects WHERE code='THACO-MOB-P2') p
CROSS JOIN (VALUES
  ('hung.pm@bbsw.vn', 'Project Manager'),
  ('duc.dev@bbsw.vn', 'Mobile Developer'),
  ('linh.dev@bbsw.vn','Frontend Developer'),
  ('hoa.qa@bbsw.vn',  'QA Engineer')
) AS r(email, role)
JOIN users u ON u.email = r.email
ON CONFLICT (project_id, user_id) DO NOTHING;

INSERT INTO members (project_id, user_id, role, updated_at)
SELECT p.id, u.id, r.role, NOW()
FROM (SELECT id FROM projects WHERE code='MTL-LOGISTICS') p
CROSS JOIN (VALUES
  ('hung.pm@bbsw.vn',  'Project Manager'),
  ('tung.ba@bbsw.vn',  'Business Analyst'),
  ('duc.dev@bbsw.vn',  'Odoo Developer'),
  ('minh.dev@bbsw.vn', 'Backend Developer'),
  ('hoa.qa@bbsw.vn',   'QA Engineer')
) AS r(email, role)
JOIN users u ON u.email = r.email
ON CONFLICT (project_id, user_id) DO NOTHING;

-- ─── MILESTONES ───────────────────────────────────────────────
INSERT INTO milestones (name, status, due_date, description, project_id, task_count, done_count, completion_pct, updated_at)
VALUES
  ('M1: Phân tích & Thiết kế',   'DONE',        '2026-02-28', 'Thu thập yêu cầu, thiết kế DB và UI/UX',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'), 5, 5, 100, NOW()),
  ('M2: Backend API Core',        'IN_PROGRESS', '2026-04-30', 'Xây dựng các API CRUD cho module CRM cốt lõi',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'), 8, 5, 63, NOW()),
  ('M3: Frontend & UAT',          'PLANNED',        '2026-06-15', 'Hoàn thiện giao diện và kiểm thử nghiệm thu',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'), 6, 0, 0, NOW()),

  ('Sprint 1: Analysis & Setup',  'DONE',        '2026-03-31', 'Phân tích gap và cài đặt môi trường Odoo 19',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'), 4, 4, 100, NOW()),
  ('Sprint 2: Core Migration',    'IN_PROGRESS', '2026-05-31', 'Migration dữ liệu master và custom module Phase 1',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'), 7, 3, 43, NOW()),
  ('Sprint 3: Testing & Go-Live', 'PLANNED',        '2026-07-31', 'UAT, training và go-live',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'), 5, 0, 0, NOW()),

  ('Phase 1: Foundation',         'IN_PROGRESS', '2026-05-31', 'Auth, project/task CRUD, basic dashboard',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'), 10, 7, 70, NOW()),
  ('Phase 2: AI Agent',           'PLANNED',        '2026-07-31', 'Text-to-SQL, checkin bot, report generator',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'), 8, 0, 0, NOW()),

  ('Release 1.0', 'DONE', '2026-01-31', 'MVP: đăng nhập, dashboard đại lý, KPI view',
   (SELECT id FROM projects WHERE code='THACO-MOB-P2'), 12, 12, 100, NOW()),
  ('Release 1.5', 'DONE', '2026-03-31', 'Push notification, offline mode, báo cáo PDF',
   (SELECT id FROM projects WHERE code='THACO-MOB-P2'), 10, 10, 100, NOW()),

  ('GĐ1: Nền tảng + Sales + CS',      'PLANNED', '2026-05-15',
   'Tuần 1–7. Nền tảng danh mục + CRM pipeline, báo giá, quản lý lô hàng, chứng từ HBL/HAWB/DN/BBGH, OCR, Smart Alerts.',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'), 0, 0, 0, NOW()),
  ('GĐ2: Operations & Hải quan',      'PLANNED', '2026-06-26',
   'Tuần 8–13. OP quản lý hải quan, Ecus export, SOA Agent tự động hàng tuần, Container/Cargo, lưu trữ chứng từ tập trung.',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'), 0, 0, 0, NOW()),
  ('GĐ3: Báo cáo & Tự động hóa',      'PLANNED', '2026-07-24',
   'Tuần 14–17. Dashboard thời gian thực, KPI, cảnh báo, carrier tracking (webhook), NL Queries BI.',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'), 0, 0, 0, NOW()),
  ('GĐ4: Kế toán, Tài chính & VAS',   'PLANNED', '2026-09-25',
   'Tuần 18–26. VAS TT200, AR/AP, E-invoice SInvoice, Bank Recon, P&L per Shipment, Báo cáo B01/B02/B03.',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'), 0, 0, 0, NOW());

-- ─── TASKS — THACO-CRM-P1 ────────────────────────────────────
INSERT INTO tasks (name, status, priority, deadline, description, project_id, assignee_id, milestone_id, total_hours, updated_at)
VALUES
  ('Phân tích nghiệp vụ CRM', 'DONE', 'HIGH', '2026-02-10',
   'Thu thập và tài liệu hóa yêu cầu từ stakeholder THACO',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='tung.ba@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M1: Phân tích & Thiết kế'),
   40, NOW()),

  ('Thiết kế DB Schema', 'DONE', 'HIGH', '2026-02-15',
   'Thiết kế schema PostgreSQL cho module customer, lead, opportunity',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M1: Phân tích & Thiết kế'),
   24, NOW()),

  ('Wireframe & Prototype UI', 'DONE', 'MEDIUM', '2026-02-20',
   'Thiết kế wireframe các màn hình chính trong Figma',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='linh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M1: Phân tích & Thiết kế'),
   32, NOW()),

  ('API Customer Management', 'DONE', 'HIGH', '2026-03-31',
   'CRUD API cho quản lý khách hàng, liên hệ, địa chỉ',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M2: Backend API Core'),
   48, NOW()),

  ('API Lead & Opportunity', 'IN_PROGRESS', 'HIGH', '2026-05-15',
   'API quản lý lead, chuyển đổi lead → opportunity, pipeline stages',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M2: Backend API Core'),
   24, NOW()),

  ('API Report & Dashboard', 'IN_PROGRESS', 'MEDIUM', '2026-05-30',
   'API thống kê doanh số, conversion rate, KPI theo dealer',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M2: Backend API Core'),
   16, NOW()),

  ('Frontend: Customer List & Detail', 'DONE', 'HIGH', '2026-04-15',
   'Màn hình danh sách và chi tiết khách hàng, filter, search',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='linh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M2: Backend API Core'),
   40, NOW()),

  ('Frontend: Lead Pipeline', 'TODO', 'HIGH', '2026-06-01',
   'Kanban board quản lý lead, drag & drop pipeline',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='linh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M3: Frontend & UAT'),
   0, NOW()),

  ('Test API Customer Module', 'DONE', 'MEDIUM', '2026-04-20',
   'Viết và chạy test case API customer, regression test',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='hoa.qa@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M2: Backend API Core'),
   24, NOW()),

  ('Deploy staging & UAT setup', 'TODO', 'HIGH', '2026-06-10',
   'Cài đặt môi trường staging, hướng dẫn UAT cho THACO',
   (SELECT id FROM projects WHERE code='THACO-CRM-P1'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='M3: Frontend & UAT'),
   0, NOW());

-- ─── TASKS — MTL-ODOO19 ──────────────────────────────────────
INSERT INTO tasks (name, status, priority, deadline, description, project_id, assignee_id, milestone_id, total_hours, updated_at)
VALUES
  ('Gap Analysis Odoo 16→19', 'DONE', 'URGENT', '2026-03-15',
   'Phân tích các thay đổi breaking change, deprecated API giữa v16 và v19',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='duc.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 1: Analysis & Setup'),
   32, NOW()),

  ('Setup môi trường Odoo 19', 'DONE', 'HIGH', '2026-03-20',
   'Cài đặt Odoo 19, PostgreSQL 16, cấu hình Docker dev/staging',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='duc.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 1: Analysis & Setup'),
   16, NOW()),

  ('Migration dữ liệu master (Customer, Product)', 'DONE', 'HIGH', '2026-04-30',
   'Script migration data từ v16 sang v19: res.partner, product.template',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 2: Core Migration'),
   48, NOW()),

  ('Port custom module: mtl_sale_order', 'IN_PROGRESS', 'URGENT', '2026-05-20',
   'Refactor module sale order custom của MTL cho tương thích Odoo 19',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='duc.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 2: Core Migration'),
   32, NOW()),

  ('Port custom module: mtl_inventory', 'IN_PROGRESS', 'HIGH', '2026-05-25',
   'Refactor module inventory custom cho Odoo 19',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='duc.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 2: Core Migration'),
   8, NOW()),

  ('Test regression module chuẩn Odoo', 'TODO', 'HIGH', '2026-06-15',
   'Kiểm thử các module Purchase, Sale, Inventory, Accounting trên v19',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='hoa.qa@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 2: Core Migration'),
   0, NOW()),

  ('Training người dùng MTL', 'TODO', 'MEDIUM', '2026-07-15',
   'Tổ chức 3 buổi training cho team kế toán, kho, bán hàng',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='tung.ba@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 3: Testing & Go-Live'),
   0, NOW()),

  ('Go-live cutover plan', 'TODO', 'URGENT', '2026-07-25',
   'Lên kế hoạch chuyển đổi production, backup, rollback strategy',
   (SELECT id FROM projects WHERE code='MTL-ODOO19'),
   (SELECT id FROM users WHERE email='hung.pm@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Sprint 3: Testing & Go-Live'),
   0, NOW());

-- ─── TASKS — BBPM-INTERNAL ───────────────────────────────────
INSERT INTO tasks (name, status, priority, deadline, description, project_id, assignee_id, milestone_id, total_hours, updated_at)
VALUES
  ('Setup monorepo & CI/CD', 'DONE', 'HIGH', '2026-04-10',
   'Cấu hình Docker Compose, GitHub Actions, linting',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='son.devops@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   24, NOW()),

  ('Auth module (JWT + Refresh token)', 'DONE', 'HIGH', '2026-04-15',
   'Đăng nhập, refresh token, phân quyền role-based',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   32, NOW()),

  ('Project CRUD API', 'DONE', 'HIGH', '2026-04-20',
   'API tạo, cập nhật, xóa dự án, quản lý thành viên',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   40, NOW()),

  ('Task CRUD & Worklog API', 'DONE', 'HIGH', '2026-04-30',
   'API quản lý công việc, log giờ làm việc',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   36, NOW()),

  ('Dashboard UI - Project List', 'DONE', 'HIGH', '2026-05-05',
   'Giao diện danh sách dự án, filter, search, pagination',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='linh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   28, NOW()),

  ('Dashboard UI - Task Board', 'IN_PROGRESS', 'HIGH', '2026-05-25',
   'Kanban board tasks, drag & drop, inline edit',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='linh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   16, NOW()),

  ('Worklog UI & Timer', 'IN_PROGRESS', 'MEDIUM', '2026-05-30',
   'Giao diện log giờ, timer tự động, weekly summary',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='duc.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 1: Foundation'),
   12, NOW()),

  ('AI Agent: Text-to-SQL', 'TODO', 'HIGH', '2026-07-15',
   'Tích hợp LLM để convert câu hỏi tự nhiên thành SQL query',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 2: AI Agent'),
   0, NOW()),

  ('AI Agent: Checkin Bot', 'TODO', 'HIGH', '2026-07-25',
   'Bot nhận báo cáo checkin qua Gapo/Zalo, parse NLP, lưu worklog',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='duc.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 2: AI Agent'),
   0, NOW()),

  ('AI Agent: Report Generator', 'TODO', 'MEDIUM', '2026-07-30',
   'Tự động tổng hợp báo cáo tuần/tháng theo dự án và cá nhân',
   (SELECT id FROM projects WHERE code='BBPM-INTERNAL'),
   (SELECT id FROM users WHERE email='minh.dev@bbsw.vn'),
   (SELECT id FROM milestones WHERE name='Phase 2: AI Agent'),
   0, NOW());

-- ─── TASKS — MTL-LOGISTICS (kế hoạch Odoo 19) ───────────────
INSERT INTO tasks (name, status, priority, deadline, description, project_id, milestone_id, total_hours, updated_at)
VALUES
  ('[1.1] Quản lý đối tác (Partners)', 'TODO', 'HIGH', NULL,
   'Phân loại: KH, Hãng tàu, Agent, NCC, Cảng/SB; Trường tùy chỉnh logistics; AI Copilot tự điền từ tên miền

Module: 1. Danh mục HT
Loại: Native
Odoo 19: res.partner + l10n_vn (MST validation)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[1.2] Quản lý cảng & sân bay', 'TODO', 'HIGH', NULL,
   'Model mtl.port: Tên, IATA/UN Locode, Quốc gia, Loại Sea/Air; dùng khi tạo Shipment và Quotation

Module: 1. Danh mục HT
Loại: Custom
Odoo 19: Custom mtl.port',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[1.3] Loại dịch vụ (Service Type)', 'TODO', 'HIGH', NULL,
   'FCL/LCL Export/Import, Air Export/Import, Trucking FTL/LTL, Customs Clearance; kích hoạt checklist tương ứng

Module: 1. Danh mục HT
Loại: Custom
Odoo 19: Custom selection field in mtl_freight',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[1.4] Tỷ giá hối đoái tự động', 'TODO', 'HIGH', NULL,
   'Scheduled Action gọi API Ngân hàng Nhà nước VN hàng ngày 8h; cập nhật USD/EUR/CNY tự động; không nhập tay

Module: 1. Danh mục HT
Loại: Native + Config
Odoo 19: res.currency + Scheduled Action + Custom Provider',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[1.5] Quản lý mã HS Code', 'TODO', 'HIGH', NULL,
   'Custom model mtl.hs.code: Mã 8-10 số, Mô tả, Thuế suất, VAT, Mức kiểm tra; lookup khi tạo lô hàng

Module: 1. Danh mục HT
Loại: Custom',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[1.6] Bảng giá cước (Freight Pricelist)', 'TODO', 'HIGH', NULL,
   'Phí vận cước/Địa phương/Dịch vụ/Hoa hồng; nhập từ Excel hãng vận chuyển qua pricing_import_excel (đã có sẵn)

Module: 1. Danh mục HT
Loại: Custom (đã có)
Odoo 19: product.pricelist + Custom mtl.freight.rate',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.1] Pipeline bán hàng (CRM)', 'TODO', 'HIGH', NULL,
   '5 giai đoạn: Tìm kiếm -> Gặp gỡ -> Đề xuất -> Đàm phán -> Chốt hợp đồng; Kanban kéo thả; AI Lead Scoring Odoo 19

Module: 2. CRM & Bán hàng
Loại: Native
Odoo 19: crm + AI Lead Scoring (Odoo 19 native)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.2] Lập báo giá tự động (Quotation)', 'TODO', 'HIGH', NULL,
   'Chọn Tuyến+Service+Carrier -> auto-populate phí từ mtl.freight.rate; xuất PDF template MTL; AI Copilot email

Module: 2. CRM & Bán hàng
Loại: Custom
Odoo 19: sale_management + Custom mtl.freight.rate',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.3] Cấu trúc phí báo giá', 'TODO', 'HIGH', NULL,
   'Phân nhóm: Vận cước/Phí địa phương (THC/DO/BL)/Dịch vụ/Phụ phí/Hoa hồng; đơn giá VND/USD; tổng theo tỷ giá

Module: 2. CRM & Bán hàng
Loại: Native + Config
Odoo 19: sale.order.line sections + mtl.freight.rate',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.4] Gửi báo giá qua email/WhatsApp', 'TODO', 'MEDIUM', NULL,
   'Email template MTL branding; WhatsApp Quotation template Odoo 19; lịch sử giao tiếp trong chatter

Module: 2. CRM & Bán hàng
Loại: Native
Odoo 19: mail.template + whatsapp (Odoo 19 Enterprise)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.5] Chuyển báo giá thành lô hàng', 'TODO', 'HIGH', NULL,
   'Xác nhận Sale Order -> tự động tạo mtl.shipment với đầy đủ thông tin; CS nhận thông báo

Module: 2. CRM & Bán hàng
Loại: Custom
Odoo 19: Custom automation Odoo 19',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.6] Activity Plans (Odoo 19)', 'TODO', 'HIGH', NULL,
   'Chuỗi hoạt động tự động theo dõi; nhắc nhở gọi điện/email/họp; bảng điều khiển quá hạn; Activity Plans mới

Module: 2. CRM & Bán hàng
Loại: Native
Odoo 19: crm.activity + Activity Plans (Odoo 19 new)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.8] KPI Dashboard Sales', 'TODO', 'HIGH', NULL,
   'Giá trị Pipeline, Tỷ lệ thắng, Doanh thu MTD/YTD, Top KH, Doanh thu theo Dịch vụ/Tuyến; NL Queries; thay SALES MONTHLY.xlsx

Module: 2. CRM & Bán hàng
Loại: Native
Odoo 19: crm + sale reports + Spreadsheet + NL Queries',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[2.9] Công cụ so sánh giá (Price Comparison Wizard)', 'TODO', 'HIGH', NULL,
   'So sánh giá cước các hãng vận chuyển cho cùng tuyến + loại dịch vụ trước khi báo giá; chọn hãng tối ưu

Module: 2. CRM & Bán hàng
Loại: Custom
Odoo 19: Custom mtl.price.comparison wizard',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.1] Tạo & quản lý lô hàng', 'TODO', 'HIGH', NULL,
   'mtl.shipment: 7 loại dịch vụ; auto-sequence MTL/2026/0001; tabs: Thông tin, Hàng hóa, Chứng từ, Tài chính, Lịch sử

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom mtl_freight (mtl.shipment model)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.2] Vòng đời lô hàng (8 giai đoạn)', 'TODO', 'HIGH', NULL,
   'Draft -> Booking Sent -> Booking Confirmed -> In Transit -> Arrived -> Customs Clearance -> Delivered -> Closed

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom statusbar widget in mtl_freight',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.3] Tracking tàu/máy bay', 'TODO', 'HIGH', NULL,
   'ETD/ETA thực tế vs dự kiến; Vessel/Flight/Voyage; Cutoff date; Free Time; lịch sử thay đổi ETA

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom tab Routing in mtl.shipment',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.6] Booking Management', 'TODO', 'HIGH', NULL,
   'mtl.booking per Shipment: Hãng vận chuyển, Loại, Ngày gửi, Booking Ref, Cutoff, Trạng thái Chờ/Đã xác nhận/Đã hủy

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom mtl.booking model',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.7] Checklist chứng từ tự động', 'TODO', 'HIGH', NULL,
   'Auto-checklist theo service type; FCL Export: SI -> Booking -> BKG Conf -> VGM -> HBL -> MBL -> DN; % hoàn thành

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom mtl.shipment.checklist model',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.8] Smart Alerts (cảnh báo tự động)', 'TODO', 'HIGH', NULL,
   'ETA/Cutoff/Checklist quá hạn -> thông báo trong ứng dụng + email + WhatsApp khẩn; Scheduled Action kiểm tra hàng ngày

Module: 3. Quản lý lô hàng
Loại: Native + Custom
Odoo 19: Automated Actions + whatsapp module',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.10] Arrival Notice tự động (CS)', 'TODO', 'HIGH', NULL,
   'Tự động tạo Arrival Notice khi Shipment = Arrived; email/WhatsApp gửi KH và người nhận hàng tự động

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom Automated Action + mail.template + whatsapp',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.1] HBL – House Bill of Lading', 'TODO', 'HIGH', NULL,
   'QWeb PDF chuẩn FIATA: Shipper/Consignee/Notify/POL/POD/Vessel/Container/Cargo/HS; HBL Draft Workflow

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report_mtl_hbl + Approval workflow',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.2] HAWB – House Air Waybill', 'TODO', 'HIGH', NULL,
   'QWeb PDF chuẩn IATA: Shipper/Consignee/Airport/Flight/MAWB/Pieces/Weight; auto-sequence MTLA/2026/0001

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report_mtl_hawb',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.3] Debit Note (DN)', 'TODO', 'HIGH', NULL,
   'DN gửi Agent/KH từ danh sách phí lô hàng; đa tiền tệ USD/VND; tự động chuyển thành Hóa đơn khi xác nhận GĐ4

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report_mtl_debit_note',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.4] BBGH – Biên bản giao hàng', 'TODO', 'HIGH', NULL,
   'QWeb PDF: thông tin lô hàng, ngày giao, người giao/nhận, danh sách hàng, eSignature (Sign module Odoo 19)

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report_mtl_bbgh + sign module',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.8] Mẫu Email & WhatsApp', 'TODO', 'MEDIUM', NULL,
   'Mẫu riêng cho: gửi HBL, DN, SOA, cảnh báo ETA; tự động điền thông tin lô hàng; lịch sử trong chatter lô hàng

Module: 4. Chứng từ
Loại: Native + Config
Odoo 19: mail.template + whatsapp.template (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.9] Quy trình duyệt HBL bản nháp', 'TODO', 'HIGH', NULL,
   'HBL Nháp -> Gửi khách hàng -> KH phê duyệt -> Phát hành; bước phê duyệt; chữ ký KH qua Sign/email

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom Approval Workflow + sign module',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[4.10] Xác nhận Booking PDF theo từng hãng vận chuyển', 'TODO', 'HIGH', NULL,
   'PDF xác nhận Booking theo mẫu từng hãng CMA/MSC/MSK/HPL; gửi trực tiếp từ mtl.booking

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report per carrier template',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[8.1] Email tập trung + AI', 'TODO', 'HIGH', NULL,
   'SMTP MTL domain; bí danh thư đến theo lô hàng; AI soạn thảo phản hồi; lịch sử email trong chatter

Module: 8. Tích hợp & AI
Loại: Native
Odoo 19: mail + discuss + AI (Odoo 19 native)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[8.3] Tỷ giá tự động', 'TODO', 'HIGH', NULL,
   'Scheduled cập nhật tỷ giá; cập nhật res.currency.rate; không nhập tay nữa

Module: 8. Tích hợp & AI
Loại: Native + Custom
Odoo 19: res.currency + Scheduled Action + Custom Provider',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[8.4] Import bảng giá từ Excel', 'TODO', 'HIGH', NULL,
   'pricing_import_excel wizard: upload file Excel carrier -> preview mapping -> import; cập nhật theo hiệu lực

Module: 8. Tích hợp & AI
Loại: Custom (đã có)
Odoo 19: Custom pricing_import_excel (existing module)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[8.5] Nhận dạng tài liệu thông minh (OCR)', 'TODO', 'HIGH', NULL,
   'Upload Packing List/SI -> OCR tự động trích xuất thông tin hàng hóa vào lô hàng; upload PDF nhà cung cấp -> tự điền vào Bill

Module: 8. Tích hợp & AI
Loại: Enterprise
Odoo 19: Documents Intelligence (Odoo 19 native Enterprise)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ1: Nền tảng + Sales + CS'),
   0, NOW()),

  ('[3.4] Quản lý Container (FCL)', 'TODO', 'HIGH', NULL,
   'Tab Containers: Container No, Seal No, Size 20/40/40HC, Gross Weight, CBM; dữ liệu cho VGM và HBL

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom mtl.container model',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[3.5] Quản lý thông tin hàng hóa', 'TODO', 'HIGH', NULL,
   'Tab Hàng hóa: Mô tả, Số lượng, Trọng lượng, CBM, tra cứu HS Code; cờ DG -> UN Number/IMDG Class/Nhóm đóng gói

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: Custom mtl_freight Cargo tab',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[3.9] Báo cáo tác nghiệp hàng ngày (Daily Operations Report)', 'TODO', 'HIGH', NULL,
   'Dạng danh sách thay DAILY REPORT Excel; lọc ETA hôm nay/tuần; Intelligent Gantt Odoo 19 với trạng thái màu sắc

Module: 3. Quản lý lô hàng
Loại: Native + Custom
Odoo 19: Custom list view + Intelligent Gantt (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[4.5] SOA – Statement of Accounting', 'TODO', 'HIGH', NULL,
   'Tác vụ tự động hàng tuần tạo + gửi email SOA cho Agents; tổng hợp tất cả DN trong kỳ; thay thế SOA Excel hàng tuần

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report_mtl_soa + Scheduled Action',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[4.6] Manifest Air/LCL', 'TODO', 'MEDIUM', NULL,
   'PDF tổng hợp tất cả HAWB/HBL trong 1 chuyến: thông tin Chuyến bay/Tàu, danh sách hàng, tổng trọng lượng/CBM

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom report_mtl_manifest',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[4.7] Lưu trữ & Tìm kiếm chứng từ', 'TODO', 'HIGH', NULL,
   'Không gian làm việc tài liệu theo lô hàng; upload SI/Hóa đơn/PL/BL/MAWB; tag tự động; tìm kiếm đa chiều; phân quyền RBAC

Module: 4. Chứng từ
Loại: Enterprise
Odoo 19: documents (Odoo 19 Enterprise)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[4.11] Xuất Manifest theo mẫu của MTL', 'TODO', 'MEDIUM', NULL,
   'Xuất file Manifest theo chuẩn MTL

Module: 4. Chứng từ
Loại: Custom
Odoo 19: Custom MTL export format',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[5.1] Quy trình khai báo hải quan (Customs Declaration Workflow)', 'TODO', 'HIGH', NULL,
   'mtl.customs.declaration: Draft -> Review -> Customer Approved -> Submitted -> Customs Response -> Completed

Module: 5. Hải quan (OP)
Loại: Custom
Odoo 19: Custom mtl_customs + Studio Approval Rules',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[5.2] Checklist chứng từ nhập khẩu', 'TODO', 'HIGH', NULL,
   'Danh sách kiểm tra tự động theo HS Code + loại hàng: Hóa đơn, PL, BL, CO, Giấy phép; tích hợp không gian tài liệu

Module: 5. Hải quan (OP)
Loại: Custom
Odoo 19: Custom checklist + documents module',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[5.3] Xuất dữ liệu cho Ecus', 'TODO', 'MEDIUM', NULL,
   'Nút Export for Ecus -> file Excel/CSV chuẩn import Ecus; không thay thế Ecus; giảm nhập tay vào Ecus

Module: 5. Hải quan (OP)
Loại: Custom
Odoo 19: Custom Ecus export wizard',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[5.4] Theo dõi kết quả thông quan', 'TODO', 'HIGH', NULL,
   'Phân luồng xanh/vàng/đỏ; số tờ khai; ngày thông quan; Cán bộ hải quan; hiển thị trên lô hàng cho kế toán

Module: 5. Hải quan (OP)
Loại: Custom
Odoo 19: Custom mtl.customs.declaration fields',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[5.5] Chi phí hải quan', 'TODO', 'HIGH', NULL,
   'Thuế nhập khẩu, VAT, Phí kiểm tra, Phí lưu container/lưu kho; tổng hợp vào chi phí lô hàng (tính lợi nhuận ở GĐ4)

Module: 5. Hải quan (OP)
Loại: Custom
Odoo 19: Custom mtl.customs.declaration costs',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[8.9] Email báo cáo tác nghiệp hàng ngày tự động', 'TODO', 'MEDIUM', NULL,
   'Tác vụ tự động 8h sáng gửi Báo cáo tác nghiệp qua email cho CS/OP manager; danh sách lô hàng cần xử lý hôm nay

Module: 8. Tích hợp & AI
Loại: Native + Custom
Odoo 19: Scheduled Action + mail.template',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ2: Operations & Hải quan'),
   0, NOW()),

  ('[7.1] Bảng điều khiển Sales', 'TODO', 'HIGH', NULL,
   'Giá trị Pipeline, Tỷ lệ thắng, Doanh thu MTD/YTD, Top khách hàng, theo Dịch vụ/Tuyến; chỉ số AI Lead Scoring; NL Queries

Module: 7. Báo cáo & Dashboard
Loại: Native
Odoo 19: crm + Spreadsheet + NL Queries (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[7.2] Bảng điều khiển vận hành', 'TODO', 'HIGH', NULL,
   'KPI lô hàng đang hoạt động, cảnh báo ETA, Checklist % hoàn thành, danh sách quá hạn; Intelligent Gantt đầy đủ; màu sắc theo trạng thái

Module: 7. Báo cáo & Dashboard
Loại: Native + Custom
Odoo 19: Custom views + Intelligent Gantt (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[7.4] Báo cáo doanh thu tháng', 'TODO', 'HIGH', NULL,
   'Doanh thu theo Khách hàng/Nhân viên kinh doanh/Loại dịch vụ/Tuyến; Pivot Table; NL Queries; xuất Excel; thay SALES MONTHLY.xlsx

Module: 7. Báo cáo & Dashboard
Loại: Native
Odoo 19: sale reports + Spreadsheet + NL Queries',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[7.7] KPI nhân viên', 'TODO', 'MEDIUM', NULL,
   'Số lô hàng xử lý theo CS/OP/Sales; thời gian xử lý trung bình theo loại lô hàng; tỷ lệ thắng Sales; Bộ lọc kỳ toàn cục

Module: 7. Báo cáo & Dashboard
Loại: Native + Custom
Odoo 19: Custom report + Spreadsheet + Global Filters (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[8.7] Tích hợp theo dõi hãng vận chuyển (Carrier Tracking)', 'TODO', 'LOW', NULL,
   'ir.webhook Odoo 19 nhận cập nhật tracking từ API Maersk/CMA/EMC; tự động cập nhật ETA; giảm kiểm tra thủ công

Module: 8. Tích hợp & AI
Loại: Custom
Odoo 19: ir.webhook (Odoo 19 new feature)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[8.8] Trạng thái hoàn thành công việc liên phòng ban', 'TODO', 'HIGH', NULL,
   'Bảng điều khiển hiển thị % hoàn thành từng bộ phận CS/OP/Sales/Kế toán cho mỗi lô hàng; BGĐ giám sát tổng thể

Module: 8. Tích hợp & AI
Loại: Custom
Odoo 19: Custom view + Spreadsheet',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[3.12] Theo dõi qua API hãng vận chuyển (tự động ETD/ETA)', 'TODO', 'MEDIUM', NULL,
   'Webhook nhận tracking thời gian thực từ hãng vận chuyển; cập nhật ETA tự động; không cần kiểm tra trang hãng thủ công

Module: 3. Quản lý lô hàng
Loại: Custom
Odoo 19: ir.webhook (Odoo 19 new) + Custom',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[NL-01] Đào tạo NL Queries – BGĐ', 'TODO', 'MEDIUM', NULL,
   'Hướng dẫn BGĐ/Manager dùng truy vấn ngôn ngữ tự nhiên cho báo cáo linh hoạt; ví dụ: Top 5 KH tháng này

Module: 7. Báo cáo & Dashboard
Loại: Native
Odoo 19: Spreadsheet NL Queries (Odoo 19 native)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ3: Báo cáo & Tự động hóa'),
   0, NOW()),

  ('[6.1] Hệ thống tài khoản (Chart of Accounts – VAS TT200)', 'TODO', 'HIGH', NULL,
   'Hệ thống TK theo TT200/2014: TK131(KH), TK331(NCC), TK511(DT DV), TK627/641/642(Chi phí); Phân tích chi phí theo lô hàng

Module: 6. Kế toán
Loại: Native
Odoo 19: l10n_vn (Odoo 19 native) + account module',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.2] Fiscal Positions – VAT logistics', 'TODO', 'HIGH', NULL,
   '0% VAT dịch vụ xuất khẩu, 10% VAT nhập khẩu/nội địa, miễn thuế; Fiscal Position theo loại dịch vụ; kiểm tra kỹ trước khi triển khai

Module: 6. Kế toán
Loại: Native + Config
Odoo 19: account.fiscal.position (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.3] Đa tiền tệ VAS (Multi-currency)', 'TODO', 'HIGH', NULL,
   'Hóa đơn USD/EUR -> báo cáo VND; TK413 chênh lệch tỷ giá; dùng tỷ giá bán NHTM (không ECB); lãi/lỗ tỷ giá tự động

Module: 6. Kế toán
Loại: Native + Config
Odoo 19: account multi-currency + l10n_vn',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.4] Hóa đơn từ Debit Note (AR)', 'TODO', 'HIGH', NULL,
   'DN xác nhận -> 1 click Tạo hóa đơn; account.move out_invoice với dòng phí, ánh xạ thuế, gán số Shipment/HBL/HAWB

Module: 6. Kế toán
Loại: Native + Custom
Odoo 19: account + Custom automation',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.5] Hóa đơn nhà cung cấp (AP) gán lô hàng', 'TODO', 'HIGH', NULL,
   'Nhập bill từ Hãng vận chuyển/Agent/NCC; gán lô hàng cụ thể; đối chiếu: bill nào thuộc lô nào; OCR PDF nhà cung cấp tự động

Module: 6. Kế toán
Loại: Native + Enterprise
Odoo 19: account in_invoice + Documents Intelligence',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.6] AR Aging – Công nợ phải thu', 'TODO', 'HIGH', NULL,
   'Công nợ phải thu theo khách hàng: hiện tại, 1-30, 31-60, 60+ ngày; lọc theo lô hàng/Nhân viên kinh doanh; thay KE TOAN CN PHAI THU xlsx

Module: 6. Kế toán
Loại: Native
Odoo 19: account_reports Aged Receivable',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.7] AP Aging – Công nợ phải trả', 'TODO', 'HIGH', NULL,
   'Công nợ phải trả theo Hãng vận chuyển/Agent; cảnh báo đến hạn thanh toán; phân loại theo loại dịch vụ; thay KE TOAN CN PHAI TRA xlsx

Module: 6. Kế toán
Loại: Native
Odoo 19: account_reports Aged Payable',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.8] E-Invoice – SInvoice (Viettel)', 'TODO', 'HIGH', NULL,
   'Cài đặt -> Kế toán -> Tích hợp Việt Nam -> thông tin SInvoice; phát hành HĐĐT trực tiếp từ Hóa đơn

Module: 6. Kế toán
Loại: Native
Odoo 19: l10n_vn_edi_viettel (Odoo 19 native)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.9] Đề nghị thanh toán (Payment Request)', 'TODO', 'MEDIUM', NULL,
   'NV tạo -> Manager OP/CS duyệt L1 -> Kế toán trưởng duyệt L2 -> Thực hiện TT; thay Mẫu ĐNTT.xls

Module: 6. Kế toán
Loại: Custom
Odoo 19: Custom mtl.payment.request + Studio Approval Rules',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.10] Statement of Account (đối chiếu công nợ)', 'TODO', 'MEDIUM', NULL,
   'Tổng hợp Invoice/Payment của một KH/Agent trong kỳ -> PDF; email tự động cuối tháng; thay mẫu BB đối chiếu CN

Module: 6. Kế toán
Loại: Custom
Odoo 19: Custom report + Scheduled Action',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.11] Đối soát ngân hàng (Bank Reconciliation)', 'TODO', 'HIGH', NULL,
   'Nhập sao kê ngân hàng CSV/OFX; Smart Reconciliation tự động khớp; OCR sao kê PDF; chuẩn ISO20022

Module: 6. Kế toán
Loại: Native + Enterprise
Odoo 19: account Bank Recon + OCR (Odoo 19 Enterprise)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.12] Lãi/lỗ theo lô hàng (P&L per Shipment)', 'TODO', 'HIGH', NULL,
   'profit_margin = Sum(Customer Invoices) - Sum(Vendor Bills) - Customs Costs; hiển thị trực tiếp trên Shipment form

Module: 6. Kế toán
Loại: Custom
Odoo 19: Custom computed field + analytic.account',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.13] Quản lý hoa hồng (Commission Management)', 'TODO', 'MEDIUM', NULL,
   'mtl.commission: Tỷ lệ hoa hồng %, Chờ duyệt/Đã duyệt/Đã thanh toán; quy trình phê duyệt; tạo Hóa đơn nhà cung cấp khi được duyệt

Module: 6. Kế toán
Loại: Custom
Odoo 19: Custom mtl.commission + Studio Approval',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.14] Đối soát Debit Note Agent (OCR)', 'TODO', 'HIGH', NULL,
   'OCR Debit Note nhận từ Agent (PDF); tự động khớp với Hóa đơn nhà cung cấp trong hệ thống; làm nổi bật sai lệch

Module: 6. Kế toán
Loại: Enterprise + Custom
Odoo 19: Documents Intelligence + Custom reconciliation',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.15] Kiểm tra đầy đủ chi phí lô hàng', 'TODO', 'HIGH', NULL,
   'Kiểm tra: tất cả chi phí lô hàng đã nhập đủ trước khi đóng việc; cảnh báo kế toán khi lợi nhuận âm bất thường

Module: 6. Kế toán
Loại: Custom
Odoo 19: Custom validation + Automated Action',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[6.16] Export sang Fast Accounting', 'TODO', 'MEDIUM', NULL,
   'Bút toán -> Excel chuẩn Fast; dùng song song GĐ1-3; chuyển đổi hoàn toàn khi kế toán MTL sẵn sàng

Module: 6. Kế toán
Loại: Custom
Odoo 19: Custom export wizard',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[7.3] Bảng điều khiển Tài chính + Báo cáo Lãi/Lỗ', 'TODO', 'HIGH', NULL,
   'Công nợ phải thu AR, AP đến hạn, Dòng tiền, Doanh thu vs Chi phí theo tháng; Pivot Lãi/Lỗ theo Khách hàng/Tuyến/Dịch vụ; xem chi tiết AR

Module: 7. Báo cáo & Dashboard
Loại: Native + Enterprise
Odoo 19: account + Spreadsheet + NL Queries (Odoo 19)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW()),

  ('[7.5] Báo cáo tài chính VAS', 'TODO', 'HIGH', NULL,
   'B01-DN (Bảng CĐKT), B02-DN (Kết quả HKDD), B03-DN (LCTT); B09-DN qua Viindoo module hoặc Word template

Module: 7. Báo cáo & Dashboard
Loại: Native + Optional
Odoo 19: l10n_vn (Odoo 19 native) + Viindoo (optional)',
   (SELECT id FROM projects WHERE code='MTL-LOGISTICS'),
   (SELECT id FROM milestones WHERE name='GĐ4: Kế toán, Tài chính & VAS'),
   0, NOW());

-- ─── WORKLOGS ─────────────────────────────────────────────────
INSERT INTO worklogs (work_date, description, hours, task_id, project_id, user_id, updated_at)
SELECT d.work_date, d.description, d.hours,
  (SELECT t.id FROM tasks t
   JOIN projects p ON p.id = t.project_id
   WHERE t.name = d.task_name AND p.code = d.project_code),
  (SELECT id FROM projects WHERE code = d.project_code),
  (SELECT id FROM users WHERE email = d.email),
  NOW()
FROM (VALUES
  -- THACO-CRM-P1
  ('2026-05-05'::date,'Implement customer list API, phân trang',         6,'API Customer Management',         'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-06'::date,'Unit test API customer',                          4,'API Customer Management',         'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-07'::date,'Review & fix bug customer search',                3,'API Customer Management',         'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-08'::date,'Viết test case customer module',                  6,'Test API Customer Module',        'THACO-CRM-P1','hoa.qa@bbsw.vn'),
  ('2026-05-09'::date,'Regression test, report bug',                     4,'Test API Customer Module',        'THACO-CRM-P1','hoa.qa@bbsw.vn'),
  ('2026-05-12'::date,'API lead create, update, assign',                 7,'API Lead & Opportunity',          'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-13'::date,'API opportunity pipeline',                        5,'API Lead & Opportunity',          'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-14'::date,'Thiết kế màn hình customer list Figma',           5,'Frontend: Customer List & Detail','THACO-CRM-P1','linh.dev@bbsw.vn'),
  ('2026-05-15'::date,'Implement customer list UI',                      7,'Frontend: Customer List & Detail','THACO-CRM-P1','linh.dev@bbsw.vn'),
  ('2026-05-16'::date,'Customer detail page, edit form',                 6,'Frontend: Customer List & Detail','THACO-CRM-P1','linh.dev@bbsw.vn'),
  ('2026-05-19'::date,'API dashboard: doanh số theo tháng',              6,'API Report & Dashboard',          'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-20'::date,'API KPI dealer report',                           4,'API Report & Dashboard',          'THACO-CRM-P1','minh.dev@bbsw.vn'),
  ('2026-05-21'::date,'Fix bug pagination customer list',                3,'Frontend: Customer List & Detail','THACO-CRM-P1','linh.dev@bbsw.vn'),
  ('2026-05-22'::date,'Lead list UI layout',                             4,'API Lead & Opportunity',          'THACO-CRM-P1','minh.dev@bbsw.vn'),
  -- MTL-ODOO19
  ('2026-05-05'::date,'Phân tích module sale_order custom code',         6,'Port custom module: mtl_sale_order','MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-06'::date,'Refactor ORM v16 → v19 sale order',              7,'Port custom module: mtl_sale_order','MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-07'::date,'Fix compute fields deprecated API',               4,'Port custom module: mtl_sale_order','MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-08'::date,'Start phân tích mtl_inventory module',            4,'Port custom module: mtl_inventory', 'MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-12'::date,'Refactor inventory quant logic',                  6,'Port custom module: mtl_inventory', 'MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-13'::date,'Fix migration script product template',           5,'Migration dữ liệu master (Customer, Product)','MTL-ODOO19','minh.dev@bbsw.vn'),
  ('2026-05-14'::date,'Test migration 10k records customer',             4,'Migration dữ liệu master (Customer, Product)','MTL-ODOO19','minh.dev@bbsw.vn'),
  ('2026-05-19'::date,'Tiếp tục port mtl_sale_order views',              5,'Port custom module: mtl_sale_order','MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-20'::date,'Review code sale_order với PM',                   3,'Port custom module: mtl_sale_order','MTL-ODOO19','duc.dev@bbsw.vn'),
  ('2026-05-21'::date,'Chuẩn bị test plan regression Odoo chuẩn',       4,'Test regression module chuẩn Odoo', 'MTL-ODOO19','hoa.qa@bbsw.vn'),
  -- BBPM-INTERNAL
  ('2026-05-05'::date,'Implement task board kanban layout',              6,'Dashboard UI - Task Board','BBPM-INTERNAL','linh.dev@bbsw.vn'),
  ('2026-05-06'::date,'Drag & drop task giữa columns',                  5,'Dashboard UI - Task Board','BBPM-INTERNAL','linh.dev@bbsw.vn'),
  ('2026-05-07'::date,'Task inline edit, priority badge',                4,'Dashboard UI - Task Board','BBPM-INTERNAL','linh.dev@bbsw.vn'),
  ('2026-05-08'::date,'Worklog form UI, date picker',                    5,'Worklog UI & Timer',       'BBPM-INTERNAL','duc.dev@bbsw.vn'),
  ('2026-05-09'::date,'Connect worklog API, validation',                 4,'Worklog UI & Timer',       'BBPM-INTERNAL','duc.dev@bbsw.vn'),
  ('2026-05-12'::date,'Timer component, localStorage persist',           3,'Worklog UI & Timer',       'BBPM-INTERNAL','duc.dev@bbsw.vn'),
  ('2026-05-13'::date,'Fix filter task board bug',                       2,'Dashboard UI - Task Board','BBPM-INTERNAL','linh.dev@bbsw.vn'),
  ('2026-05-19'::date,'Responsive task board mobile',                    5,'Dashboard UI - Task Board','BBPM-INTERNAL','linh.dev@bbsw.vn'),
  ('2026-05-20'::date,'Weekly worklog summary view',                     3,'Worklog UI & Timer',       'BBPM-INTERNAL','duc.dev@bbsw.vn')
) AS d(work_date, description, hours, task_name, project_code, email);

-- ─── UPDATE PROJECT COUNTERS ──────────────────────────────────
UPDATE projects p SET
  task_count      = (SELECT COUNT(*)    FROM tasks t     WHERE t.project_id = p.id),
  member_count    = (SELECT COUNT(*)    FROM members m   WHERE m.project_id = p.id),
  worklog_count   = (SELECT COUNT(*)    FROM worklogs w  WHERE w.project_id = p.id),
  milestone_count = (SELECT COUNT(*)    FROM milestones ms WHERE ms.project_id = p.id),
  total_hours     = COALESCE((SELECT SUM(hours)      FROM worklogs w WHERE w.project_id = p.id), 0),
  updated_at      = NOW();

-- ─── UPDATE MILESTONE COUNTERS (chỉ project MTL-LOGISTICS) ─────
-- Các milestone seed cũ cố tình set số liệu giả lập nên không đụng tới;
-- riêng project kế hoạch Odoo mới (task chưa phân công, toàn TODO) tính lại
-- để task_count/done_count/completion_pct khớp số task thực tế đã chèn.
UPDATE milestones ms SET
  task_count     = (SELECT COUNT(*) FROM tasks t WHERE t.milestone_id = ms.id),
  done_count     = (SELECT COUNT(*) FROM tasks t WHERE t.milestone_id = ms.id AND t.status = 'DONE'),
  completion_pct = COALESCE(ROUND(100.0 * (SELECT COUNT(*) FROM tasks t WHERE t.milestone_id = ms.id AND t.status = 'DONE')
                     / NULLIF((SELECT COUNT(*) FROM tasks t WHERE t.milestone_id = ms.id), 0)), 0),
  updated_at = NOW()
WHERE ms.project_id = (SELECT id FROM projects WHERE code = 'MTL-LOGISTICS');

-- ─── GAPO USER MAPS ──────────────────────────────────────────
-- Liên kết tài khoản Gapo Work ↔ user nội bộ (bot tra để biết tin nhắn của ai).
-- Dùng subquery theo email để không phụ thuộc thứ tự serial id.
INSERT INTO gapo_user_maps (user_id, gapo_user_id, gapo_thread_id, gapo_full_name)
SELECT id, 608678190, 1779201401766, 'Đặng Trần Tấn Lực'
FROM users WHERE email = 'luc@bbsw.vn'
ON CONFLICT (user_id) DO NOTHING;

-- ─── VERIFY ──────────────────────────────────────────────────
SELECT 'users'         AS tbl, COUNT(*) FROM users
UNION ALL SELECT 'projects',       COUNT(*) FROM projects
UNION ALL SELECT 'members',        COUNT(*) FROM members
UNION ALL SELECT 'milestones',     COUNT(*) FROM milestones
UNION ALL SELECT 'tasks',          COUNT(*) FROM tasks
UNION ALL SELECT 'worklogs',       COUNT(*) FROM worklogs
UNION ALL SELECT 'gapo_user_maps', COUNT(*) FROM gapo_user_maps
ORDER BY tbl;
