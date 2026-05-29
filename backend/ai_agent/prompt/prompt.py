SCHEMA_COMPACT = """
Tables:
companies(id,name,code,currency_id)
users(id,full_name,email,role,department,position,company_id,active,is_super_admin)
projects(id,name,code,status,priority,start_date,end_date,description,total_hours,estimated_total_hours,task_count,member_count,worklog_count,scope_count,milestone_count,customer_name,company_id,owner_id,account_manager_id,currency_id)
members(id,project_id,user_id,role,joined_at)
milestones(id,project_id,name,status,due_date,description,completion_pct,task_count,done_count)
tasks(id,name,status,priority,deadline,end_at,description,issues,result,total_hours,project_id,company_id,assignee_id,milestone_id,currency_id)
scopes(id,project_id,task_id,assignee_id,sequence,name,notes,estimated_hours,currency_id)
worklogs(id,work_date,description,hours,task_id,project_id,company_id,user_id,source,slot)
backlogs(id,status,source,work_date,description,hours,task_id,project_id,company_id,user_id,currency_id,approver_id,approved_at,rejected_reason)

Relations:
users.company_id=companies.id
projects.company_id=companies.id
tasks.company_id=companies.id
worklogs.company_id=companies.id
backlogs.company_id=companies.id
tasks.project_id=projects.id
milestones.project_id=projects.id
members.project_id=projects.id
scopes.project_id=projects.id
worklogs.project_id=projects.id
backlogs.project_id=projects.id
tasks.assignee_id=users.id
scopes.assignee_id=users.id
worklogs.user_id=users.id
backlogs.user_id=users.id
backlogs.approver_id=users.id
members.user_id=users.id
worklogs.task_id=tasks.id
backlogs.task_id=tasks.id
tasks.milestone_id=milestones.id
scopes.task_id=tasks.id

Enums:
projects.status: PLANNED, PENDING, IN_PROGRESS, DONE, CANCELLED
tasks.status: TODO, IN_PROGRESS, DONE, CANCELLED
backlogs.status: PENDING, APPROVED, REJECTED
backlogs.source: manual, checkin, import
priority: LOW, MEDIUM, HIGH, URGENT
users.role: ADMIN, MANAGER, MEMBER, VIEWER, SUPER_ADMIN

Rules:
running_project = projects.status='IN_PROGRESS'
pending_project = projects.status='PENDING'
cancelled_project = projects.status='CANCELLED'
done_project = projects.status='DONE'
active_project = projects.status NOT IN ('DONE','CANCELLED')
done_task = tasks.status='DONE'
remaining_task = tasks.status<>'DONE'
todo_task = tasks.status='TODO'
cancelled_task = tasks.status='CANCELLED'
overdue_task = tasks.deadline<CURRENT_DATE AND tasks.status<>'DONE'
milestone_progress = milestones.completion_pct
project_progress = DONE tasks / total tasks
project_hours = projects.total_hours
project_estimated_hours = projects.estimated_total_hours
approved_backlog_hours = SUM(backlogs.hours) WHERE backlogs.status='APPROVED'
pending_backlog = backlogs.status='PENDING'
cost/budget fields were removed; do not query budget,total_cost,budget_remaining,estimated_total_cost,estimated_cost,estimated_rate,cost_per_hour_snapshot,total_cost_snapshot,member_rates.
"""
