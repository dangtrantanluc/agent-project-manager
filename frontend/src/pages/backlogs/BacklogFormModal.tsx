import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { backlogCreateSchema, type BacklogCreateInput } from "@bb-pm/shared";
import { createProjectBacklog, updateBacklog, type Backlog } from "@/features/backlogs/api";
import { listTasks } from "@/features/tasks/api";
import { Modal } from "@/components/ui/Modal";
import { DateField } from "@/components/ui/DateField";
import { useState, useEffect } from "react";

export function BacklogFormModal({
  open,
  onClose,
  projectId,
  taskId: preselectedTaskId,
  backlog,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  taskId?: number;
  backlog?: Backlog | null;
}) {
  const qc = useQueryClient();
  const [taskId, setTaskId] = useState<number | undefined>(preselectedTaskId ?? backlog?.task?.id);

  const tasksQ = useQuery({
    queryKey: ["tasks-lite", projectId],
    queryFn: () => listTasks({ projectId, pageSize: 500 }),
    enabled: open,
  });

  const form = useForm<BacklogCreateInput>({
    resolver: zodResolver(backlogCreateSchema),
    defaultValues: {
      workDate: new Date().toISOString().slice(0, 10),
      hours: 1,
      description: "",
    },
  });

  useEffect(() => {
    if (backlog) {
      form.reset({
        workDate: backlog.workDate.slice(0, 10),
        hours: Number(backlog.hours),
        description: backlog.description ?? "",
      });
      setTaskId(backlog.task?.id);
    } else if (open) {
      form.reset({ workDate: new Date().toISOString().slice(0, 10), hours: 1, description: "" });
      setTaskId(preselectedTaskId);
    }
  }, [backlog, open]);

  const save = useMutation({
    mutationFn: async (v: BacklogCreateInput) => {
      if (backlog) return updateBacklog(backlog.id, v);
      return createProjectBacklog(projectId, { ...v, taskId });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["backlogs"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks", { projectId }] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={backlog ? "Sửa backlog" : "Log giờ làm việc"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        {!backlog && (
          <div>
            <label className="label">Task (tùy chọn)</label>
            <select
              className="input"
              value={taskId ?? ""}
              onChange={(e) => setTaskId(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">— Không gắn task —</option>
              {tasksQ.data?.data.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Ngày *</label>
            <DateField form={form} name="workDate" />
          </div>
          <div>
            <label className="label">Giờ *</label>
            <input
              type="number"
              step="0.25"
              min="0.25"
              max="24"
              className="input"
              {...form.register("hours", { valueAsNumber: true })}
            />
          </div>
        </div>

        <div>
          <label className="label">Mô tả</label>
          <textarea rows={3} className="input" {...form.register("description")} />
        </div>

        {save.isError && <p className="text-sm text-red-600">{(save.error as any)?.message ?? "Có lỗi"}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {save.isPending ? "Đang lưu…" : "Lưu"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
