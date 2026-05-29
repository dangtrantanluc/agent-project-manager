TEXT2SQL_TEST_CASES = [
    {
        "id": "count_projects",
        "question": "Hiện tại có bao nhiêu dự án?",
        "llm_sql": """
            SELECT COUNT(*) AS total_projects
            FROM projects p;
        """,
        "expected_sql_contains": ["count", "projects"],
        "tenant_tables": ["projects"],
    },
    {
        "id": "list_active_projects",
        "question": "Liệt kê các dự án đang hoạt động",
        "llm_sql": """
            SELECT p.id, p.name, p.status
            FROM projects p
            WHERE p.status = 'IN_PROGRESS'::"ProjectStatus"
            ORDER BY p.name ASC, p.id ASC
            LIMIT 5;
        """,
        "expected_sql_contains": ["projects", "status", "order by", "limit 5"],
        "tenant_tables": ["projects"],
    },
    {
        "id": "count_members",
        "question": "Có bao nhiêu nhân sự trong hệ thống?",
        "llm_sql": """
            SELECT COUNT(*) AS total_users
            FROM users u
            WHERE u.active = TRUE;
        """,
        "expected_sql_contains": ["count", "users", "active"],
        "tenant_tables": ["users"],
    },
    {
        "id": "tasks_by_project",
        "question": "Dự án Mobile App BB có những task nào?",
        "llm_sql": """
            SELECT t.id, t.name AS task_name, t.status, t.deadline
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            WHERE p.name ILIKE '%Mobile App BB%'
            ORDER BY t.deadline NULLS LAST, t.id ASC
            LIMIT 5;
        """,
        "expected_sql_contains": ["tasks", "projects", "ilike", "mobile app bb"],
        "tenant_tables": ["tasks", "projects"],
    },
    {
        "id": "overdue_tasks",
        "question": "Những task nào đã quá hạn?",
        "llm_sql": """
            SELECT t.id, t.name AS task_name, t.deadline, p.name AS project_name
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            WHERE t.deadline < (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
              AND t.status <> 'DONE'::"TaskStatus"
            ORDER BY t.deadline ASC, t.id ASC
            LIMIT 5;
        """,
        "expected_sql_contains": ["tasks", "deadline", "asia/ho_chi_minh", "status <> 'done'"],
        "tenant_tables": ["tasks"],
    },
    {
        "id": "developer_total_hours",
        "question": "Mỗi developer đã log tổng cộng bao nhiêu giờ?",
        "llm_sql": """
            SELECT u.id, u.full_name, SUM(w.hours) AS total_hours
            FROM worklogs w
            JOIN users u ON u.id = w.user_id
            GROUP BY u.id, u.full_name
            ORDER BY total_hours DESC, u.id ASC
            LIMIT 5;
        """,
        "expected_sql_contains": ["sum", "worklogs", "users", "group by"],
        "tenant_tables": ["worklogs", "users"],
    },
    {
        "id": "project_total_hours",
        "question": "Tổng giờ của từng dự án là bao nhiêu?",
        "llm_sql": """
            SELECT p.id, p.name AS project_name, p.total_hours
            FROM projects p
            ORDER BY p.total_hours DESC NULLS LAST, p.id ASC
            LIMIT 5;
        """,
        "expected_sql_contains": ["projects", "total_hours", "order by"],
        "tenant_tables": ["projects"],
    },
    {
        "id": "highest_hours_task",
        "question": "Task nào có tổng giờ cao nhất trong mỗi project?",
        "llm_sql": """
            WITH ranked AS (
              SELECT t.id, t.name AS task_name, t.project_id, t.total_hours,
                     ROW_NUMBER() OVER (PARTITION BY t.project_id ORDER BY t.total_hours DESC NULLS LAST, t.id ASC) AS rn
              FROM tasks t
            )
            SELECT p.name AS project_name, r.task_name, r.total_hours
            FROM ranked r
            JOIN projects p ON p.id = r.project_id
            WHERE r.rn = 1
            ORDER BY p.name ASC;
        """,
        "expected_sql_contains": ["with", "row_number", "tasks", "projects", "total_hours"],
        "tenant_tables": ["tasks", "projects"],
    },
]

TEXT2SQL_INVALID_CASES = [
    {
        "id": "irrelevant_question",
        "question": "Hôm nay thời tiết thế nào?",
        "llm_sql": "SELECT 'INVALID_QUESTION' AS error;",
        "expected_sql_contains": ["invalid_question"],
    }
]

# Các case này thuộc semantic parser/router layer, không phải Text2SQLAgent.
ROUTER_LEVEL_CASES = [
    {
        "id": "multi_intent_project_progress",
        "question": "Hiện tại có bao nhiêu dự án và tiến độ từng dự án như nào?",
        "expected_sql_count_min": 2,
        "expected_intents": ["count_projects", "project_progress"],
    }
]
