# Plan code-level: ActionAgent registry + change_assignee / delete_task / remove_member

> Spec sẵn-implement. Mỗi giai đoạn có file, chữ ký hàm, SQL, và điểm kiểm thử cụ thể.
> Đọc kèm: message_router.py (_run_agent, _combine_results, _PAYLOAD_GATES, handle_message),
> task_create_service.py, add_member_service.py, entity_resolver.py.

## RÀNG BUỘC CỨNG đã xác minh từ code

1. **`_run_agent` PHẢI trả `str`** khi đi qua `asyncio.gather` + `_combine_results`
   (message_router.py:388 ép `str(result).strip()`; test_router_fallback.py:181 assert `out.lower()`).
   → ActionResult.confirm KHÔNG sống sót qua đường gộp nhiều-agent.
2. **Nút bấm/menu đính qua `metadata["menu"]`** (xem _task_menu_reply:325-330, handle_message:252-254).
   → confirm phải đi đường "single intent" giống `if agent_names == ["task_update"]` (245-258),
   KHÔNG qua _run_agent/_combine.
3. **task_update là intent độc quyền** xử lý riêng (245-258) — KHÔNG đụng.
4. Notifier có sẵn: `notify_task_assigned(task_id, assignee_id, actor_id)` (fire-and-forget).
5. RiskAlert: `RiskAlertService.trigger_for_project(project_id)` (staticmethod, nền).

## QUYẾT ĐỊNH KIẾN TRÚC seam (hệ quả của ràng buộc #1, #2)

Action tool chia 2 đường trong handle_message:
- **Đường A (gộp được)**: action KHÔNG confirm + chạy chung agent khác → qua _run_agent trả `.message` (str).
- **Đường B (single, có thể confirm)**: khi `agent_names` chỉ gồm 1 action tool → xử lý riêng
  TRƯỚC vòng gather (giống task_update), nhận `ActionResult` đầy đủ, đính confirm vào menu.

Thêm helper trong message_router:
```python
ACTION_SINGLE = ACTION_NAMES  # set tên action
# trong handle_message, ngay sau khối if agent_names == ["task_update"]:
if len(agent_names) == 1 and agent_names[0] in ACTION_NAMES:
    return await self._run_single_action(agent_names[0], message, user_id,
                                          channel, thread_id, metadata,
                                          memory_context, user_profile)
```
`_run_single_action` gọi `ACTION_REGISTRY[name].run(ctx)` → ActionResult; nếu `need_confirm`
đính `metadata["menu"]`; ngược lại trả `AgentReply(answer=result.message, agent=name)`.
Trong `_run_agent` (đường gộp) action vẫn gọi `.run()` nhưng `return result.message` (str).

---

## GIAI ĐOẠN A1 — shared/action_base.py (FILE MỚI)

```python
"""Khung chung cho các 'write action qua chat' (giao việc, thêm/gỡ thành viên,
đổi người, xoá task...). Gom boilerplate: init LLM, extract, gate quyền."""
import logging, os
from dataclasses import dataclass
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel
from ai_agent.shared.entity_resolver import is_privileged

logger = logging.getLogger(__name__)

@dataclass
class ActionResult:
    status: str                 # ok|forbidden|need_info|not_found|ambiguous|exists|error|need_confirm|done
    message: str
    entity_id: int | None = None
    menu: list | None = None    # nút bấm khi need_confirm (shape giống task menu)

@dataclass
class ActionContext:
    message: str
    sender_user_id: str | int
    user_profile: dict
    memory_context: str = ""
    timezone_name: str = "Asia/Ho_Chi_Minh"
    thread_id: str | None = None
    channel: str = "gapo"

    @property
    def sender_id_int(self) -> int | None:
        try: return int(self.sender_user_id)
        except (TypeError, ValueError): return None


class ActionAgentBase:
    # Con PHẢI khai:
    name: str
    intent_desc: str            # 1 dòng cho prompt router
    extraction_model: type[BaseModel]
    system_prompt: str
    purpose: str                # cho make_llm
    forbidden_msg: str = "Chỉ quản lý (MANAGER/ADMIN) mới thao tác được. Bạn nhờ quản lý giúp nhé."
    llm_unavailable_msg: str = "Mình chưa xử lý qua chat được lúc này, bạn thao tác trên web giúp nhé."
    needs_confirm: bool = False

    def __init__(self, llm=None):
        self._llm = None
        model, api_key, base_url = os.getenv("MODEL_NAME"), os.getenv("API_KEY"), os.getenv("BASE_URL")
        if llm is not None:
            self._llm = llm.with_structured_output(self.extraction_model, method="function_calling")
        elif model and api_key and base_url:
            from ai_agent.shared.llm_factory import make_llm
            base = make_llm(purpose=self.purpose, timeout=15, max_retries=1, temperature=0.1,
                            reasoning_effort="none", model=model, api_key=api_key, base_url=base_url)
            self._llm = base.with_structured_output(self.extraction_model, method="function_calling")
        else:
            logger.warning("%s LLM chưa cấu hình.", type(self).__name__)

    def _extra_prompt(self, ctx: ActionContext) -> str:
        return ""    # create_task override để chèn "Ngày hôm nay"

    async def _extract(self, ctx: ActionContext):
        memory_block = f"Ngữ cảnh trước:\n{ctx.memory_context}\n\n" if ctx.memory_context else ""
        try:
            return await self._llm.ainvoke([
                SystemMessage(content=self.system_prompt + self._extra_prompt(ctx)),
                HumanMessage(content=f"{memory_block}Câu của người dùng:\n{ctx.message}"),
            ])
        except Exception:
            logger.exception("%s bóc tách lỗi", type(self).__name__)
            return None

    async def run(self, ctx: ActionContext) -> ActionResult:
        if not is_privileged(ctx.user_profile.get("role")):
            return ActionResult("forbidden", self.forbidden_msg)
        if self._llm is None:
            return ActionResult("error", self.llm_unavailable_msg)
        extraction = await self._extract(ctx)
        if extraction is None:
            return ActionResult("error", self.llm_unavailable_msg)
        return await self._handle(extraction, ctx)

    async def _handle(self, extraction, ctx: ActionContext) -> ActionResult:
        raise NotImplementedError
```
**Test A1** (test_action_base.py): subclass dummy → run với role MEMBER → forbidden; _llm=None → error.

---

## GIAI ĐOẠN A2 — Chuyển 2 service cũ sang base

### task_create_service.py
- Khai class: `class TaskCreateService(ActionAgentBase)` với
  `name="create_task"`, `purpose="create_task"`, `extraction_model=TaskCreateExtraction`,
  `system_prompt=_EXTRACT_SYSTEM_PROMPT`, `intent_desc="- create_task: người dùng GIAO VIỆC..."`.
- Override `_extra_prompt`: `return f"\nNgày hôm nay: {today}"` (today theo TZ VN — giữ logic cũ).
- Xoá `__init__`, `_extract` (lên base).
- Đổi tên `create_from_chat` → `_handle(self, extraction, ctx)`; trả `ActionResult` thay `TaskCreateResult`.
  Map status cũ→mới: created→"done", forbidden→base lo, need_info/not_found/ambiguous/error giữ.
- **Tương thích test cũ**: giữ wrapper:
  ```python
  async def create_from_chat(self, *, message, sender_user_id, user_profile=None,
                             memory_context="", timezone_name="Asia/Ho_Chi_Minh"):
      r = await self.run(ActionContext(message, sender_user_id, user_profile or {},
                                        memory_context, timezone_name))
      return TaskCreateResult(status=r.status, message=r.message, task_id=r.entity_id)
  ```
  (test_task_create_service.py vẫn gọi create_from_chat, assert .status/.task_id/.message → xanh.)

### add_member_service.py — tương tự, wrapper `add_from_chat` map về AddMemberResult.

**Test A2**: test_task_create_service.py + test_add_member_service.py chạy KHÔNG sửa.

---

## GIAI ĐOẠN A3 — router/action_registry.py (FILE MỚI) + message_router

```python
from app.services.task_create_service import TaskCreateService
from app.services.add_member_service import AddMemberService
# (sau) from app.services.change_assignee_service import ChangeAssigneeService ...

_INSTANCES = {}
def _get(cls):
    if cls not in _INSTANCES: _INSTANCES[cls] = cls()   # lazy-init
    return _INSTANCES[cls]

ACTION_CLASSES = {
    "create_task": TaskCreateService,
    "add_member":  AddMemberService,
}
ACTION_NAMES = set(ACTION_CLASSES)
def get_action(name): return _get(ACTION_CLASSES[name])
# Mô tả intent cho router prompt — đọc từ class attr, KHÔNG khởi tạo instance:
ACTION_INTENT_DESCS = {n: c.intent_desc for n, c in ACTION_CLASSES.items()}
```
> intent_desc đặt là **class attribute** (không cần instance) để router import không kéo theo make_llm.

### message_router.py thay đổi
1. `__init__`: bỏ `self.task_create_service`, `self.add_member_service` (chuyển vào registry).
2. handle_message — thêm SAU khối task_update (sau dòng 258):
   ```python
   if len(agent_names) == 1 and agent_names[0] in ACTION_NAMES:
       from ai_agent.router.action_registry import get_action
       ctx = ActionContext(message=message, sender_user_id=user_id,
                           user_profile=user_profile or {}, memory_context=memory_context,
                           timezone_name=self._timezone_name(metadata),
                           thread_id=thread_id, channel=channel)
       res = await get_action(agent_names[0]).run(ctx)
       md = {**metadata}
       if res.menu: md["menu"] = res.menu
       return AgentReply(answer=res.message, agent=agent_names[0], metadata=md)
   ```
3. `_run_agent` — xoá 2 nhánh create_task/add_member, thay bằng (đường gộp, trả str):
   ```python
   if agent_name in ACTION_NAMES:
       from ai_agent.router.action_registry import get_action
       res = await get_action(agent_name).run(ActionContext(
           message=message, sender_user_id=user_id, user_profile=user_profile or {},
           memory_context=memory_context, timezone_name=self._timezone_name(metadata),
           thread_id=thread_id, channel=channel))
       return res.message   # confirm bị bỏ ở đường gộp — chấp nhận (xem ràng buộc #1)
   ```
**Test A3**: full suite. Câu "giao task..." single → đường mới; câu "report + giao task" gộp → .message.

---

## GIAI ĐOẠN A4 — router.py

```python
from ai_agent.router.action_registry import ACTION_NAMES, ACTION_INTENT_DESCS
READ_AGENTS = {"report","text2sql","planning","conversation","notification","task_update"}
VALID_AGENTS = READ_AGENTS | ACTION_NAMES
```
Trong `_classify` prompt — phần intent action sinh từ ACTION_INTENT_DESCS:
```python
action_lines = "\n".join(ACTION_INTENT_DESCS.values())
prompt = f"""...danh mục đọc...
{action_lines}
..."""
```
> Vòng import: router.py → action_registry (chỉ tên + class attr desc) → services. KHÔNG ngược.

---

## GIAI ĐOẠN C4 — entity_resolver.py: +resolve_tasks (làm TRƯỚC C1)

```python
import re
_TASK_CODE = re.compile(r"\[?\d+(?:\.\d+)*\]?")

async def resolve_tasks(db, ref: str, sender_id: int) -> list[dict]:
    """Tìm task theo MÃ ([3.2]/code) hoặc TÊN, trong phạm vi quyền người gọi
    (task thuộc dự án sender owner/AM/member/assignee). Trả [{id,name,code,project_id,assignee_id}]."""
    ref = (ref or "").strip()
    scope = """
      AND t.project_id IN (
        SELECT p.id FROM projects p WHERE p.owner_id=:s OR p.account_manager_id=:s
        UNION SELECT m.project_id FROM members m WHERE m.user_id=:s
        UNION SELECT t2.project_id FROM tasks t2 WHERE t2.assignee_id=:s)"""
    code_m = _TASK_CODE.fullmatch(ref) or _TASK_CODE.search(ref)
    if code_m:    # ưu tiên khớp MÃ chính xác
        code = code_m.group(0).strip("[]")
        rows = (await db.execute(text(f"""
            SELECT t.id,t.name,t.code,t.project_id,t.assignee_id FROM tasks t
            WHERE t.code = :code {scope}"""), {"code": code, "s": sender_id})).fetchall()
        if rows: return [_row(r) for r in rows]
    like = f"%{ref.lower()}%"     # fallback TÊN
    rows = (await db.execute(text(f"""
        SELECT t.id,t.name,t.code,t.project_id,t.assignee_id FROM tasks t
        WHERE lower(t.name) LIKE :like {scope}
          AND t.status::text NOT IN ('DONE','CANCELLED')
        ORDER BY t.updated_at DESC LIMIT 10"""), {"like": like, "s": sender_id})).fetchall()
    return [_row(r) for r in rows]
# _row: dict(id,name,code,project_id,assignee_id)
```
**Test C4** (test_task_resolver.py): fake session; ref "[3.2]" → match code; tên mơ hồ → ≥2 rows.

---

## GIAI ĐOẠN C1 — change_assignee_service.py (FILE MỚI, KHÔNG confirm)

```python
class ChangeAssigneeExtraction(BaseModel):
    task_ref: str = ""
    new_assignee: str = ""
    assign_to_self: bool = False

class ChangeAssigneeService(ActionAgentBase):
    name = "change_assignee"
    intent_desc = ("- change_assignee: GIAO LẠI một task ĐÃ CÓ cho người khác "
                   '(vd "chuyển task [3.2] cho Thảo", "task X để Nam làm"). Khác create_task (tạo mới).')
    purpose = "change_assignee"
    extraction_model = ChangeAssigneeExtraction
    system_prompt = """Bóc tách yêu cầu GIAO LẠI task cho người khác.
- task_ref: mã [x.y] hoặc tên task cần chuyển. Bắt buộc.
- new_assignee: TÊN người nhận mới (bỏ kính ngữ). Rỗng nếu tự nhận.
- assign_to_self: true nếu "cho tôi/mình". Mặc định false.
Không phải giao lại -> để rỗng hết."""

    async def _handle(self, ex, ctx):
        if not ex.task_ref.strip() or not (ex.new_assignee.strip() or ex.assign_to_self):
            return ActionResult("need_info", 'Bạn cho mình rõ: chuyển **task nào** cho **ai** nhé. Vd "chuyển task [3.2] cho Thảo".')
        sid = ctx.sender_id_int
        async with AsyncSessionLocal() as db:
            tasks = await resolve_tasks(db, ex.task_ref, sid)
            task, err = resolve_one(tasks, ex.task_ref, "task", "name")
            if err: return ActionResult("not_found" if not tasks else "ambiguous", err)
            if ex.assign_to_self and not ex.new_assignee.strip():
                new = {"user_id": sid, "full_name": ctx.user_profile.get("full_name","bạn")}
            else:
                users = await resolve_users(db, ex.new_assignee.strip(), sid)
                new, err = resolve_one(users, ex.new_assignee, "người", "full_name")
                if err: return ActionResult("not_found" if not users else "ambiguous", err)
            await db.execute(text("UPDATE tasks SET assignee_id=:a, updated_at=NOW() WHERE id=:t"),
                             {"a": new["user_id"], "t": task["id"]})
            # audit('change_assignee_from_chat', {...})
            await db.commit()
        import asyncio
        asyncio.create_task(notify_task_assigned(task_id=task["id"], assignee_id=new["user_id"], actor_id=sid))
        asyncio.create_task(_trigger_risk(task["project_id"]))   # RiskAlertService.trigger_for_project
        code = f"[{task['code']}] " if task.get("code") else ""
        return ActionResult("done", f"Đã chuyển task {code}**{task['name']}** cho **{new['full_name']}**. Mình đã báo bạn ấy rồi nhé.", entity_id=task["id"])
```
Đăng ký: thêm `"change_assignee": ChangeAssigneeService` vào ACTION_CLASSES.
Keyword (intent_rules, tối thiểu): `CHANGE_ASSIGNEE_KEYWORDS=("chuyển task","giao lại","đổi người")`.
**Test C1**: resolve task+người OK → done + notify gọi; task mơ hồ → ambiguous; thiếu info → need_info.

---

## GIAI ĐOẠN B — Cơ chế CONFIRM (làm trước C2/C3)

delete/remove resolve ở lượt 1 → trả need_confirm + menu nút bấm; lượt 2 bấm → handler xoá.

### message_router._PAYLOAD_GATES — thêm prefix ACTDEL
```python
{"prefix": "ACTDEL|", "method": None, "parse": _parse_actdel, "session": None,
 "reply": "confirm_delete"},   # xử lý riêng — gọi handler xoá theo kind
```
`_parse_actdel("ACTDEL|task|12")` -> ("task", 12). Trong _dispatch_task_payload thêm nhánh
`reply=="confirm_delete"`: theo kind gọi `get_action("delete_task")._do_delete(id, sender)` hoặc
`get_action("remove_member")._do_remove(id, sender)`. (handler xoá KHÔNG cần LLM — id đã có.)

### ActionResult.menu khi need_confirm
```python
ActionResult("need_confirm",
  f"Bạn chắc muốn xoá task {code}**{name}**? Hành động KHÔNG hoàn tác.",
  menu=[{"label":"✅ Xác nhận xoá","payload":f"ACTDEL|task|{tid}"},
        {"label":"⛔ Huỷ","payload":TASKCANCEL_PAYLOAD}])
```
Đường _run_single_action đính menu này vào metadata (đã có ở A3).

**Test B**: lượt 1 trả need_confirm + payload đúng; bấm ACTDEL|task|<id> → DELETE chạy.

---

## GIAI ĐOẠN C2 — delete_task_service.py (CÓ confirm)

```python
class DeleteTaskExtraction(BaseModel):
    task_ref: str = ""

class DeleteTaskService(ActionAgentBase):
    name="delete_task"; needs_confirm=True; purpose="delete_task"
    intent_desc='- delete_task: XOÁ một task (vd "xoá task [3.2]", "huỷ task X").'
    extraction_model=DeleteTaskExtraction
    system_prompt="Bóc tách yêu cầu XOÁ task. task_ref: mã [x.y] hoặc tên. Rỗng nếu không phải."

    async def _handle(self, ex, ctx):   # LƯỢT 1: chỉ resolve + xin confirm
        if not ex.task_ref.strip():
            return ActionResult("need_info", 'Bạn muốn xoá task nào? Cho mình mã [x.y] hoặc tên nhé.')
        async with AsyncSessionLocal() as db:
            tasks = await resolve_tasks(db, ex.task_ref, ctx.sender_id_int)
            task, err = resolve_one(tasks, ex.task_ref, "task", "name")
            if err: return ActionResult("not_found" if not tasks else "ambiguous", err)
        code = f"[{task['code']}] " if task.get("code") else ""
        return ActionResult("need_confirm",
            f"Bạn chắc muốn xoá task {code}**{task['name']}**? Hành động KHÔNG hoàn tác.",
            entity_id=task["id"],
            menu=[{"label":"✅ Xác nhận xoá","payload":f"ACTDEL|task|{task['id']}"},
                  {"label":"⛔ Huỷ","payload":TASKCANCEL_PAYLOAD}])

    async def _do_delete(self, task_id: int, sender_id: int) -> dict:   # LƯỢT 2: bấm nút
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text("SELECT name, milestone_id FROM tasks WHERE id=:t"),{"t":task_id})).fetchone()
            if not row: return {"message": "Task không còn tồn tại."}
            await db.execute(text("DELETE FROM tasks WHERE id=:t"),{"t":task_id})
            if row[1]:
                await db.execute(text("UPDATE milestones SET task_count=GREATEST(task_count-1,0) WHERE id=:m"),{"m":row[1]})
                # _recompute_milestone(row[1], db)  -- sao từ tasks/router.py
            # audit('delete_task_from_chat')
            await db.commit()
        return {"message": f"Đã xoá task **{row[0]}**."}
```
**Lưu ý sao đúng từ web** (tasks/router.py:643-665): giảm task_count + _recompute_milestone.
Quyền: MANAGER/ADMIN (base gate is_privileged đã chặn lượt 1; lượt 2 qua nút — chỉ người được
gửi menu mới bấm được, vẫn nên kiểm tra lại quyền trong _do_delete cho chắc).
**Test C2**: lượt 1→need_confirm; _do_delete→DELETE + giảm task_count.

---

## GIAI ĐOẠN C3 — remove_member_service.py (CÓ confirm)

```python
class RemoveMemberExtraction(BaseModel):
    member: str = ""
    project: str = ""

class RemoveMemberService(ActionAgentBase):
    name="remove_member"; needs_confirm=True; purpose="remove_member"
    intent_desc='- remove_member: GỠ thành viên khỏi dự án (vd "bỏ Nam khỏi dự án Logistics"). Đối lập add_member.'
    extraction_model=RemoveMemberExtraction
    system_prompt="Bóc tách yêu cầu GỠ thành viên khỏi dự án. member: tên người. project: tên dự án. Rỗng nếu không phải."

    async def _handle(self, ex, ctx):   # LƯỢT 1
        if not ex.member.strip() or not ex.project.strip():
            return ActionResult("need_info", 'Bạn cho mình rõ: gỡ **ai** khỏi **dự án nào** nhé.')
        sid = ctx.sender_id_int
        async with AsyncSessionLocal() as db:
            users = await resolve_users(db, ex.member.strip(), sid)
            user, err = resolve_one(users, ex.member, "người", "full_name")
            if err: return ActionResult("not_found" if not users else "ambiguous", err)
            projs = await resolve_projects(db, ex.project.strip(), sid)
            proj, err = resolve_one(projs, ex.project, "dự án", "name")
            if err: return ActionResult("not_found" if not projs else "ambiguous", err)
            m = (await db.execute(text("SELECT id FROM members WHERE project_id=:p AND user_id=:u"),
                                  {"p":proj["id"],"u":user["user_id"]})).fetchone()
            if not m:
                return ActionResult("exists", f"**{user['full_name']}** không ở trong dự án **{proj['name']}**.")
        return ActionResult("need_confirm",
            f"Bạn chắc muốn gỡ **{user['full_name']}** khỏi dự án **{proj['name']}**?",
            entity_id=m[0],
            menu=[{"label":"✅ Xác nhận gỡ","payload":f"ACTDEL|member|{m[0]}"},
                  {"label":"⛔ Huỷ","payload":TASKCANCEL_PAYLOAD}])

    async def _do_remove(self, member_id: int, sender_id: int) -> dict:   # LƯỢT 2
        async with AsyncSessionLocal() as db:
            row=(await db.execute(text("SELECT project_id FROM members WHERE id=:m"),{"m":member_id})).fetchone()
            if not row: return {"message":"Thành viên không còn trong dự án."}
            await db.execute(text("DELETE FROM members WHERE id=:m"),{"m":member_id})
            await db.execute(text("UPDATE projects SET member_count=GREATEST(member_count-1,0), updated_at=NOW() WHERE id=:p"),{"p":row[0]})
            # audit('remove_member_from_chat')
            await db.commit()
        return {"message":"Đã gỡ thành viên khỏi dự án."}
```
**Sao đúng từ web** (members/router.py:133-155): giảm member_count.
**Test C3**: không phải thành viên→"không ở trong"; lượt1→need_confirm; _do_remove→DELETE+giảm count.

---

## Thứ tự thực thi + cổng kiểm thử
| Bước | Làm | Cổng (test phải xanh) |
|---|---|---|
| 1 | A1 action_base | test_action_base mới |
| 2 | A2 chuyển 2 service | test_task_create + test_add_member KHÔNG sửa |
| 3 | A3 registry + message_router | full suite + test_router_fallback |
| 4 | A4 router.py | router phân loại 2 action cũ vẫn đúng |
| 5 | C4 resolve_tasks | test_task_resolver |
| 6 | C1 change_assignee | test_change_assignee + đăng ký 1 dòng |
| 7 | B confirm + ACTDEL gate | test_confirm_flow |
| 8 | C2 delete_task | test_delete_task |
| 9 | C3 remove_member | test_remove_member |
| 10 | A5 co lưới keyword (resolve_agents) | test_router_fallback cập nhật |
| 11 | README sơ đồ ActionAgent | — |

## Rủi ro
- **_TASK_CODE_RE cướp intent** (intent_rules.py:73): "xoá task [3.2]"/"chuyển [3.2]" hiện bị ép
  task_update. PHẢI xử ở bước 10 (A5) HOẶC thêm keyword delete/change ưu tiên TRƯỚC luật mã task.
  → Không làm bước 10 thì C1/C2 không route được khi câu có mã. Đây là phụ thuộc cứng.
- **confirm không qua đường gộp**: nếu user nói "xoá task X và báo cáo dự án" (delete + report
  cùng lúc) → đi đường gather, confirm mất. Chấp nhận: delete là single-intent điển hình; nếu cần,
  chặn delete/remove khỏi multi-intent ở resolve_agents (trả về chỉ tool đó).
- **Xoá nhầm**: needs_confirm 2 bước + resolve mơ hồ hỏi lại + kiểm quyền cả lượt 2.
