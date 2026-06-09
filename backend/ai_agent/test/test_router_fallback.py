"""Test logic định tuyến tất định (không LLM) của router intent + message_router.

Router là "cửa trước" của agent: chọn sai agent -> trả lời sai loại. Các hàm
thuần (deterministic) đáng test kỹ vì là lưới an toàn khi LLM router thiếu chắc
chắn:

  PMMultiAgentRouter._parse_agent_list() — chịu lỗi output LLM bẩn (fence/text/rỗng).
  AgentMessageRouter._keyword_agent()    — dò từ khoá tiếng Việt cứu intent.
  AgentMessageRouter._fallback_agent_for_message() — chuẩn hoá danh sách + loại
                                          'conversation' thừa khi có agent khác.
  AgentMessageRouter._combine_results()  — gộp output nhiều agent, không nhãn.

Không gọi LLM thật: chỉ khởi tạo router và gọi các hàm thuần. Constructor có tạo
client ChatOpenAI nhưng không phát request mạng, nên an toàn/offline.
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.router.message_router import AgentMessageRouter
from ai_agent.router.router import PMMultiAgentRouter


@pytest.fixture(scope="module")
def router():
    return AgentMessageRouter()


@pytest.fixture(scope="module")
def intent():
    return PMMultiAgentRouter()


# ---------------------------------------------------------------------------
# _parse_agent_list — chịu lỗi output LLM bẩn
# ---------------------------------------------------------------------------

def test_parse_clean_array(intent):
    assert intent._parse_agent_list('["text2sql", "report"]') == ["text2sql", "report"]


def test_parse_markdown_fence(intent):
    assert intent._parse_agent_list('```json\n["planning"]\n```') == ["planning"]


def test_parse_garbage_scans_names(intent):
    # Không có JSON array hợp lệ -> fallback quét tên agent trong text thô.
    assert set(intent._parse_agent_list("conversation và report nhé")) == {"report", "conversation"}


def test_parse_drops_invalid_names(intent):
    assert intent._parse_agent_list('["foobar", "task_update"]') == ["task_update"]


def test_parse_dedupes(intent):
    assert intent._parse_agent_list('["report","report","planning"]') == ["report", "planning"]


def test_parse_empty(intent):
    assert intent._parse_agent_list("không có gì") == []


# ---------------------------------------------------------------------------
# _keyword_agent — cứu intent bằng từ khoá tiếng Việt
# ---------------------------------------------------------------------------

KEYWORD_CASES = [
    ("tôi làm xong task rồi", "task_update"),
    ("task abc đã xong rồi", "task_update"),
    ("done nhé", "task_update"),
    ("giúp tôi lập kế hoạch sprint", "planning"),
    ("chia milestone giúp tôi", "planning"),
    ("cho mình báo cáo tiến độ", "report"),
    ("thống kê giờ làm tuần này", "report"),
    ("tạo thông báo nhắc deadline", "notification"),
    ("set reminder cho team", "notification"),
    ("dự án X có bao nhiêu task", "text2sql"),
    ("danh sách task của tôi", "text2sql"),
    ("ai là người phụ trách dự án X", "text2sql"),
    ("chào bạn, khỏe không", "conversation"),
]


@pytest.mark.parametrize("msg,expected", KEYWORD_CASES, ids=[c[0][:20] for c in KEYWORD_CASES])
def test_keyword_agent(router, msg, expected):
    assert router._keyword_agent(msg) == expected


def test_keyword_completion_claim_beats_data(router):
    # "làm xong task X": có 'task' (data) lẫn 'làm xong' (task_update) -> task_update thắng.
    assert router._keyword_agent("làm xong task X rồi") == "task_update"


def test_keyword_planning_over_data(router):
    # Câu chứa cả 'kế hoạch' (planning) lẫn 'task' (data) -> planning thắng (ưu tiên trước).
    assert router._keyword_agent("lập kế hoạch chia task") == "planning"


# ---------------------------------------------------------------------------
# _fallback_agent_for_message — chuẩn hoá + lọc 'conversation' thừa (3a)
# ---------------------------------------------------------------------------

def test_fallback_multi_kept(router):
    assert router._fallback_agent_for_message("hi", ["text2sql", "report"]) == ["text2sql", "report"]


def test_fallback_conversation_keyword_rescue(router):
    # LLM không chắc (chỉ trả conversation) + câu có từ khoá -> cứu intent.
    assert router._fallback_agent_for_message("tôi làm xong task rồi", ["conversation"]) == ["task_update"]


def test_fallback_conversation_only(router):
    assert router._fallback_agent_for_message("chào bạn", ["conversation"]) == ["conversation"]


def test_fallback_completion_claim_forces_task_update(router):
    # Root-cause fix: câu xác nhận hoàn thành PHẢI vào task_update kể cả khi LLM
    # phân nhầm sang notification/conversation. Trả ĐỘC QUYỀN ["task_update"].
    assert router._fallback_agent_for_message("tôi update rồi", ["notification"]) == ["task_update"]
    assert router._fallback_agent_for_message("xong rồi nhé", ["conversation", "notification"]) == ["task_update"]
    assert router._fallback_agent_for_message("done", ["report"]) == ["task_update"]


def test_fallback_drops_extra_conversation(router):  # 3a
    # 'conversation' kèm agent nghiệp vụ -> bỏ conversation thừa.
    assert router._fallback_agent_for_message(
        "hello b, tôi có task nào", ["text2sql", "conversation"]
    ) == ["text2sql"]


def test_fallback_empty_defaults(router):
    assert router._fallback_agent_for_message("xyz", []) == ["conversation"]


# ---------------------------------------------------------------------------
# _combine_results — ghép sạch, không nhãn (3b)
# ---------------------------------------------------------------------------

def test_combine_single(router):
    assert router._combine_results(["text2sql"], ["10 task"]) == ("10 task", ["text2sql"])


def test_combine_multi_no_labels(router):
    ans, ran = router._combine_results(["text2sql", "report"], ["10 task", "tiến độ 50%"])
    assert ran == ["text2sql", "report"]
    assert "【" not in ans
    assert ans == "10 task\n\ntiến độ 50%"


def test_combine_skips_exception(router):
    ans, ran = router._combine_results(["text2sql", "report"], [Exception("boom"), "ok"])
    assert ran == ["report"]
    assert ans == "ok"


def test_combine_all_failed(router):
    assert router._combine_results(["text2sql"], [Exception("boom")]) == ("", [])
