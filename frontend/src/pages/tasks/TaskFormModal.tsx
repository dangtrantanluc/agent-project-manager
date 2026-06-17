import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { taskCreateSchema, type TaskCreateInput, TaskStatus, Priority } from "@bb-pm/shared";
import { createTask, updateTask, listBlockers, resolveBlocker, listTasks, getTask, addDependency, removeDependency, type TaskListItem } from "@/features/tasks/api";
import { listWorklogs } from "@/features/worklogs/api";
import { listMilestones } from "@/features/milestones/api";
import { listMembers } from "@/features/members/api";
import { Modal } from "@/components/ui/Modal";
import { DateField } from "@/components/ui/DateField";
import { TagMultiSelect } from "@/components/ui/TagMultiSelect";
import { TaskSearchSelect } from "@/components/ui/TaskSearchSelect";
import { DatedNotesList } from "@/components/ui/DatedNotesList";
import { TaskActivityTimeline } from "@/components/ui/TaskActivityTimeline";
import { setTaskTags } from "@/features/tags/api";
import { useEffect, useState } from "react";
import { formatDate, formatHours } from "@/lib/format";

type UserOption = { id: number; fullName: string; email: string };

/** "đã kẹt bao lâu" tính từ created_at đến giờ — dạng ngắn gọn tiếng Việt. */
function elapsedSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const days = Math.floor(ms / 86_400_000);
  if (days >= 1) return `${days} ngày`;
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 1) return `${hours} giờ`;
  const mins = Math.max(1, Math.floor(ms / 60_000));
  return `${mins} phút`;
}

export function TaskFormModal({
  open,
  onClose,
  projectId,
  task,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  task?: TaskListItem | null;
}) {
  const qc = useQueryClient();
  const msQ = useQuery({
    queryKey: ["milestones", projectId],
    queryFn: () => listMilestones(projectId),
    enabled: open && !!projectId,
  });
  // Members of the project — for assignee dropdown
  const membersQ = useQuery({
    queryKey: ["project-members-light", projectId],
    queryFn: async () => (await listMembers(projectId)).map((m) => m.user as UserOption),
    enabled: open && !!projectId,
  });
  const worklogsQ = useQuery({
    queryKey: ["worklogs", { taskId: task?.id }],
    queryFn: () => listWorklogs({ taskId: task!.id, limit: 100 }),
    enabled: open && !!task?.id,
  });
  const blockersQ = useQuery({
    queryKey: ["blockers", { taskId: task?.id }],
    queryFn: () => listBlockers(task!.id),
    enabled: open && !!task?.id,
  });
  const resolveBlockerM = useMutation({
    mutationFn: (blockerId: number) => resolveBlocker(blockerId),
    onSuccess: () => {
      blockersQ.refetch();
      // Badge "đang kẹt" ở list/board lấy từ blockerCount -> làm mới task lists.
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  // Phụ thuộc: tải chi tiết task (để lấy dependsOn cập nhật) + danh sách task cùng dự án để chọn.
  const taskDetailQ = useQuery({
    queryKey: ["task-detail", task?.id],
    queryFn: () => getTask(task!.id),
    enabled: open && !!task?.id,
  });
  const siblingTasksQ = useQuery({
    queryKey: ["project-tasks-light", projectId],
    queryFn: () => listTasks({ projectId, pageSize: 200 }),
    enabled: open && !!projectId && !!task?.id,
  });
  const dependsOn = taskDetailQ.data?.dependsOn ?? task?.dependsOn ?? [];
  const [depError, setDepError] = useState<string | null>(null);
  const addDepM = useMutation({
    mutationFn: (depId: number) => addDependency(task!.id, depId),
    onSuccess: () => {
      setDepError(null);
      taskDetailQ.refetch();
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (e: any) => setDepError(e?.response?.data?.detail || "Không thêm được phụ thuộc."),
  });
  const removeDepM = useMutation({
    mutationFn: (depId: number) => removeDependency(task!.id, depId),
    onSuccess: () => {
      taskDetailQ.refetch();
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const form = useForm<TaskCreateInput>({
    resolver: zodResolver(taskCreateSchema),
    defaultValues: { priority: "MEDIUM", status: "TODO" },
  });
  // Nhãn quản lý ngoài react-hook-form (lưu qua API riêng PUT /tasks/:id/tags).
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  // Kết quả/Khó khăn: mặc định xem dạng timeline (DatedNotesList); bấm Sửa -> textarea thô.
  const [editResult, setEditResult] = useState(false);
  const [editIssues, setEditIssues] = useState(false);
  // Lịch sử: collapsible, chỉ fetch khi mở (lazy).
  const [showActivity, setShowActivity] = useState(false);

  useEffect(() => {
    if (task) {
      form.reset({
        name: task.name,
        status: task.status,
        priority: task.priority as any,
        deadline: task.deadline ? task.deadline.slice(0, 10) : undefined,
        endAt: task.endAt ? task.endAt.slice(0, 10) : undefined,
        description: task.description ?? undefined,
        result: task.result ?? undefined,
        issues: task.issues ?? undefined,
        assigneeId: task.assignee?.id,
        milestoneId: task.milestone?.id,
      });
      setSelectedTagIds(task.tags?.map((t) => t.id) ?? []);
      setEditResult(false);
      setEditIssues(false);
      setShowActivity(false);
    } else if (open) {
      form.reset({ priority: "MEDIUM", status: "TODO" });
      setSelectedTagIds([]);
      // Task mới chưa có lịch sử -> mở sẵn ô nhập cho tiện.
      setEditResult(true);
      setEditIssues(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task, open]);

  // <select> phải controlled: native select chỉ render đúng value khi <option> đã có
  // trong DOM, mà options (members/milestones) tải bất đồng bộ sau reset → nếu để
  // uncontrolled sẽ hiển thị "—". Đọc value từ RHF và set lại qua onChange.
  const assigneeId = form.watch("assigneeId");
  const milestoneId = form.watch("milestoneId");

  // Khi SỬA: chỉ gửi các trường người dùng thực sự thay đổi (dirty), giữ nguyên
  // mọi thông tin cũ. Khi TẠO MỚI: gửi toàn bộ form.
  const buildPatch = (v: TaskCreateInput): Partial<TaskCreateInput> => {
    const dirty = form.formState.dirtyFields as Record<string, unknown>;
    const patch: Record<string, unknown> = {};
    for (const key of Object.keys(dirty)) {
      patch[key] = (v as Record<string, unknown>)[key];
    }
    return patch as Partial<TaskCreateInput>;
  };

  const save = useMutation({
    mutationFn: async (v: TaskCreateInput) => {
      const saved = task ? await updateTask(task.id, buildPatch(v)) : await createTask(projectId, v);
      // Đồng bộ nhãn sau khi task đã có id (best-effort: lỗi nhãn không chặn lưu task).
      try {
        await setTaskTags(saved.id, selectedTagIds);
      } catch {
        /* ignore — task vẫn đã lưu */
      }
      return saved;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["worklogs"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["milestones", projectId] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["dashboard-tags-summary"] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={task ? `Sửa task${task.code ? ` ${task.code}` : ""}` : "Tạo task"} size="lg">
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="label">Tiêu đề *</label>
            <input className="input" {...form.register("name")} />
            {form.formState.errors.name && <p className="mt-1 text-xs text-red-600">{form.formState.errors.name.message}</p>}
          </div>
          <div>
            <label className="label">Trạng thái</label>
            <select className="input" {...form.register("status")}>
              {Object.values(TaskStatus).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Ưu tiên</label>
            <select className="input" {...form.register("priority")}>
              {Object.values(Priority).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Assignee</label>
            <select
              className="input"
              value={assigneeId ?? ""}
              onChange={(e) =>
                form.setValue("assigneeId", e.target.value ? Number(e.target.value) : undefined, {
                  shouldDirty: true,
                })
              }
            >
              <option value="">—</option>
              {membersQ.data?.map((u) => (
                <option key={u.id} value={u.id}>{u.fullName}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Milestone</label>
            <select
              className="input"
              value={milestoneId ?? ""}
              onChange={(e) =>
                form.setValue("milestoneId", e.target.value ? Number(e.target.value) : undefined, {
                  shouldDirty: true,
                })
              }
            >
              <option value="">—</option>
              {msQ.data?.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Deadline</label>
            <DateField form={form} name="deadline" />
            {form.formState.errors.deadline && <p className="mt-1 text-xs text-red-600">{form.formState.errors.deadline.message}</p>}
          </div>
          <div>
            <label className="label">End at <span className="font-normal text-slate-400">(tùy chọn)</span></label>
            <DateField form={form} name="endAt" />
            {form.formState.errors.endAt && <p className="mt-1 text-xs text-red-600">{form.formState.errors.endAt.message}</p>}
          </div>
          <div className="col-span-2">
            <label className="label">Nhãn</label>
            <TagMultiSelect value={selectedTagIds} onChange={setSelectedTagIds} />
          </div>
          <div className="col-span-2">
            <label className="label">Mô tả</label>
            <textarea rows={3} className="input" {...form.register("description")} />
          </div>
          <div className="col-span-2">
            <div className="mb-1 flex items-center justify-between">
              <label className="label mb-0">Kết quả</label>
              <button type="button" className="text-xs text-brand-700 hover:underline"
                onClick={() => setEditResult((e) => !e)}>
                {editResult ? "Xong" : "✏️ Sửa"}
              </button>
            </div>
            {editResult ? (
              <textarea rows={3} className="input" placeholder="Mỗi dòng 1 mục, vd: [2026-06-17] ..."
                {...form.register("result")} />
            ) : (
              <DatedNotesList text={form.watch("result")} emptyText="Chưa có kết quả." />
            )}
          </div>
          <div className="col-span-2">
            <div className="mb-1 flex items-center justify-between">
              <label className="label mb-0">Khó khăn</label>
              <button type="button" className="text-xs text-brand-700 hover:underline"
                onClick={() => setEditIssues((e) => !e)}>
                {editIssues ? "Xong" : "✏️ Sửa"}
              </button>
            </div>
            {editIssues ? (
              <textarea rows={3} className="input" placeholder="Mỗi dòng 1 mục, vd: [2026-06-17] ..."
                {...form.register("issues")} />
            ) : (
              <DatedNotesList text={form.watch("issues")} emptyText="Chưa ghi khó khăn." />
            )}
          </div>
        </div>

        {save.isError && <p className="text-sm text-red-600">Có lỗi, vui lòng thử lại.</p>}

        {task && (blockersQ.data?.some((b) => !b.resolvedAt) || (blockersQ.data?.length ?? 0) > 0) && (
          <section className="rounded-md border border-red-200 bg-red-50/40 p-3 dark:border-red-900/50 dark:bg-red-900/10">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-red-700 dark:text-red-300">⛔ Vướng mắc (blocker)</h3>
              <span className="text-xs text-slate-500">
                {blockersQ.data?.filter((b) => !b.resolvedAt).length ?? 0} chưa gỡ
              </span>
            </div>
            <ul className="space-y-1.5">
              {blockersQ.data?.map((b) => (
                <li
                  key={b.id}
                  className={`flex items-start justify-between gap-2 rounded border border-slate-100 bg-white p-2 text-xs dark:border-slate-800 dark:bg-slate-900 ${b.resolvedAt ? "opacity-60" : ""}`}
                >
                  <div className="min-w-0">
                    <p className={`text-slate-700 dark:text-slate-300 ${b.resolvedAt ? "line-through" : ""}`}>
                      {b.description || "—"}
                    </p>
                    <p className="mt-0.5 text-slate-400">
                      {b.resolvedAt
                        ? `Đã gỡ ${formatDate(b.resolvedAt)}`
                        : `Đã kẹt ${elapsedSince(b.createdAt)} · báo ${formatDate(b.createdAt)}`}
                    </p>
                  </div>
                  {!b.resolvedAt && (
                    <button
                      type="button"
                      className="btn-ghost shrink-0 border border-slate-200 px-2 py-1 text-xs dark:border-slate-700"
                      disabled={resolveBlockerM.isPending}
                      onClick={() => resolveBlockerM.mutate(b.id)}
                    >
                      ✅ Đã gỡ
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {task && (
          <section className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">🔗 Phụ thuộc (cần xong trước)</h3>
              <span className="text-xs text-slate-500">{dependsOn.length} task</span>
            </div>
            {dependsOn.length > 0 && (
              <ul className="mb-2 space-y-1.5">
                {dependsOn.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-2 rounded border border-slate-100 bg-white p-2 text-xs dark:border-slate-800 dark:bg-slate-900">
                    <span className="min-w-0 truncate">
                      {d.code && <span className="mr-1.5 font-mono text-slate-400">{d.code}</span>}
                      {d.name}
                      {d.status !== "DONE" && <span className="ml-1.5 text-amber-600">● chưa xong</span>}
                    </span>
                    <button
                      type="button"
                      className="btn-ghost shrink-0 border border-slate-200 px-2 py-1 text-xs dark:border-slate-700"
                      disabled={removeDepM.isPending}
                      onClick={() => removeDepM.mutate(d.id)}
                    >
                      Gỡ
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <TaskSearchSelect
              disabled={addDepM.isPending}
              options={(siblingTasksQ.data?.data ?? [])
                .filter((t) => t.id !== task.id && !dependsOn.some((d) => d.id === t.id))
                .map((t) => ({ id: t.id, code: t.code, name: t.name }))}
              onSelect={(id) => addDepM.mutate(id)}
            />
            {depError && <p className="mt-1 text-xs text-red-600">{depError}</p>}
          </section>
        )}

        {task && (
          <section className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Worklog đã ghi</h3>
              <span className="text-xs text-slate-500">{worklogsQ.data?.meta.total ?? 0} worklog</span>
            </div>
            {worklogsQ.isLoading ? (
              <p className="py-4 text-center text-sm text-slate-500">Đang tải worklog...</p>
            ) : worklogsQ.data?.data.length ? (
              <div className="max-h-44 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-slate-500">
                    <tr>
                      <th className="py-1 pr-2">Ngày</th>
                      <th className="py-1 pr-2">Giờ</th>
                      <th className="py-1">Nội dung</th>
                    </tr>
                  </thead>
                  <tbody>
                    {worklogsQ.data.data.map((w) => (
                      <tr key={w.id} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="whitespace-nowrap py-2 pr-2 text-slate-500">{formatDate(w.workDate)}</td>
                        <td className="whitespace-nowrap py-2 pr-2 font-medium">{formatHours(w.hours)}</td>
                        <td className="py-2 text-slate-700 dark:text-slate-300">{w.description || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="py-4 text-center text-sm text-slate-500">Task này chưa có worklog.</p>
            )}
          </section>
        )}

        {task && (
          <section className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <button type="button" className="flex w-full items-center justify-between"
              onClick={() => setShowActivity((s) => !s)}>
              <h3 className="text-sm font-semibold">🕓 Lịch sử</h3>
              <span className="text-xs text-slate-500">{showActivity ? "Ẩn ▲" : "Xem ▼"}</span>
            </button>
            {showActivity && (
              <div className="mt-2">
                <TaskActivityTimeline taskId={task.id} enabled={showActivity} />
              </div>
            )}
          </section>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {save.isPending ? "Đang lưu…" : "Lưu"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
