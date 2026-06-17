"""Test ĐỊNH TUYẾN tất định cho 3 write-action mới (change_assignee/delete_task/
remove_member) + registry.

Trọng tâm: keyword của delete/remove/change phải ưu tiên TRƯỚC luật _TASK_CODE_RE
(câu có mã [x.y] mặc định về task_update). Nếu sai thứ tự, "xoá task [3.2]" sẽ bị
cướp về task_update — bug đã được cảnh báo trong plan.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.router.intent_rules import resolve_agents
from ai_agent.router.action_registry import ACTION_NAMES, ACTION_INTENT_DESCS, get_action
from ai_agent.router.router import VALID_AGENTS
from ai_agent.shared.action_base import ActionAgentBase
from ai_agent.shared.entity_resolver import _TASK_CODE_JIRA, _TASK_CODE_NUM


# ── Bắt mã task: phải nhận Jira-style THẬT ("GAP-T0003") lẫn dạng số "[3.2]" ──
# (Regression: bản đầu chỉ bắt [x.y] nên "xoá task GAP-T0003" không resolve được.)
def test_task_code_regex_matches_jira_and_numeric():
    assert _TASK_CODE_JIRA.search("xoá task GAP-T0003").group(1) == "GAP-T0003"
    assert _TASK_CODE_JIRA.search("chuyển NHAP-T9 cho ai đó").group(1) == "NHAP-T9"
    assert _TASK_CODE_NUM.search("chuyển task [3.2] cho Thảo").group(1) == "3.2"
    # Mã Jira KHÔNG bị regex số bắt nhầm phần đuôi.
    assert _TASK_CODE_NUM.search("GAP-T0003") is None


# ── Registry hợp lệ ──────────────────────────────────────────────────────────
def test_registry_names_subset_of_valid_agents():
    assert ACTION_NAMES <= VALID_AGENTS
    assert {"create_task", "add_member", "change_assignee",
            "delete_task", "remove_member"} <= ACTION_NAMES


def test_every_action_is_base_subclass_and_lazy_instantiates():
    for name in ACTION_NAMES:
        act = get_action(name)
        assert isinstance(act, ActionAgentBase)
        assert act.name == name


def test_intent_descs_cover_all_actions():
    assert set(ACTION_INTENT_DESCS) == ACTION_NAMES


# ── Định tuyến: delete/remove/change ưu tiên trước mã task ───────────────────
def test_delete_with_task_code_not_stolen_by_task_update():
    # "xoá task [3.2]" có mã -> KHÔNG được rơi về task_update.
    assert resolve_agents("xoá task [3.2]", ["conversation"]) == ["delete_task"]


def test_delete_by_name():
    assert resolve_agents("huỷ task tài liệu API", ["conversation"]) == ["delete_task"]


def test_change_assignee_with_task_code():
    assert resolve_agents("chuyển task [3.2] cho Thảo", ["conversation"]) == ["change_assignee"]


def test_change_assignee_giao_lai():
    assert resolve_agents("giao lại task tài liệu cho Nam", ["conversation"]) == ["change_assignee"]


def test_remove_member():
    assert resolve_agents("gỡ thành viên Nam khỏi dự án Logistics", ["conversation"]) == ["remove_member"]


def test_plain_task_code_still_task_update():
    # Câu nêu mã nhưng KHÔNG phải delete/change -> giữ hành vi cũ (task_update).
    assert resolve_agents("task [3.2] sao rồi nhỉ", ["conversation"]) == ["task_update"]


def test_create_task_not_confused_with_change():
    # "giao task ... cho ..." (tạo mới) KHÁC "giao lại" (đổi người).
    assert resolve_agents("giao task Viết API cho Thảo deadline mai", ["conversation"]) == ["create_task"]
