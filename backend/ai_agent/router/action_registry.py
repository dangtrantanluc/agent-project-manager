"""Registry các write-action (ActionAgentBase).

Thêm 1 tool ghi-dữ-liệu = thêm 1 dòng vào ACTION_CLASSES (không sửa router/_run_agent).

- ``ACTION_NAMES``: tập tên hợp lệ — router gộp vào VALID_AGENTS.
- ``ACTION_INTENT_DESCS``: mô tả intent cho prompt router, đọc qua CLASS ATTRIBUTE
  (không khởi tạo instance -> router import không kéo theo make_llm).
- ``get_action(name)``: trả instance (lazy-init, dùng lại) để message_router gọi run().

KHÔNG đưa task_update vào đây: nó có phiên Redis + menu nút bấm + verify service
riêng, xử lý ở nhánh độc quyền trong message_router.
"""
from app.services.task_create_service import TaskCreateService
from app.services.add_member_service import AddMemberService
from app.services.change_assignee_service import ChangeAssigneeService
from app.services.delete_task_service import DeleteTaskService
from app.services.remove_member_service import RemoveMemberService

# name -> class (chưa khởi tạo). intent_desc là class attribute nên đọc được ngay.
ACTION_CLASSES = {
    "create_task": TaskCreateService,
    "add_member": AddMemberService,
    "change_assignee": ChangeAssigneeService,
    "delete_task": DeleteTaskService,
    "remove_member": RemoveMemberService,
}

ACTION_NAMES = set(ACTION_CLASSES)
ACTION_INTENT_DESCS = {name: cls.intent_desc for name, cls in ACTION_CLASSES.items()}

# Lazy-init: chỉ dựng service (kéo theo make_llm) khi thực sự chạy tool đó.
_INSTANCES: dict[str, object] = {}


def get_action(name: str):
    """Trả instance service cho ``name`` (khởi tạo lần đầu rồi dùng lại)."""
    if name not in _INSTANCES:
        _INSTANCES[name] = ACTION_CLASSES[name]()
    return _INSTANCES[name]
