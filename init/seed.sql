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
   (SELECT id FROM projects WHERE code='THACO-MOB-P2'), 10, 10, 100, NOW());

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
