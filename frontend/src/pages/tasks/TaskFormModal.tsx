import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { taskCreateSchema, type TaskCreateInput, TaskStatus, Priority } from "@bb-pm/shared";
import { createTask, updateTask, type TaskListItem } from "@/features/tasks/api";
import { listWorklogs } from "@/features/worklogs/api";
import { listMilestones } from "@/features/milestones/api";
import { listMembers } from "@/features/members/api";
import { Modal } from "@/components/ui/Modal";
import { DateField } from "@/components/ui/DateField";
import { useEffect } from "react";
import { formatDate, formatHours } from "@/lib/format";

type UserOption = { id: number; fullName: string; email: string };

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

  const form = useForm<TaskCreateInput>({
    resolver: zodResolver(taskCreateSchema),
    defaultValues: { priority: "MEDIUM", status: "TODO" },
  });

  useEffect(() => {
    if (task) {
      form.reset({
        name: task.name,
        status: task.status,
        priority: task.priority as any,
        deadline: task.deadline ? task.deadline.slice(0, 10) : undefined,
        endAt: task.endAt ? task.endAt.slice(0, 10) : undefined,
        description: task.description ?? undefined,
        assigneeId: task.assignee?.id,
        milestoneId: task.milestone?.id,
      });
    } else if (open) {
      form.reset({ priority: "MEDIUM", status: "TODO" });
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
    mutationFn: async (v: TaskCreateInput) =>
      task ? updateTask(task.id, buildPatch(v)) : createTask(projectId, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["worklogs"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["milestones", projectId] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={task ? "Sửa task" : "Tạo task"} size="lg">
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
          </div>
          <div>
            <label className="label">End at</label>
            <DateField form={form} name="endAt" />
          </div>
          <div className="col-span-2">
            <label className="label">Mô tả</label>
            <textarea rows={3} className="input" {...form.register("description")} />
          </div>
        </div>

        {save.isError && <p className="text-sm text-red-600">Có lỗi, vui lòng thử lại.</p>}

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
