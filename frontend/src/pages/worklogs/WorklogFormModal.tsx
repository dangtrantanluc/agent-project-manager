import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { worklogUpdateSchema, type WorklogUpdateInput } from "@/shared/schemas/worklog";
import { createWorklog, updateWorklog, type Worklog, type WorklogCreateInput } from "@/features/worklogs/api";
import { listTasks } from "@/features/tasks/api";
import { Modal } from "@/components/ui/Modal";
import { useState, useEffect } from "react";
import { z } from "zod";
import { toast } from "sonner";

const createSchema = z.object({
  workDate: z.string().date(),
  hours: z.coerce.number().min(0.25).max(24),
  description: z.string().optional(),
});
type CreateFields = z.infer<typeof createSchema>;

export function WorklogFormModal({
  open,
  onClose,
  projectId,
  taskId: preselectedTaskId,
  worklog,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  taskId?: number;
  worklog?: Worklog | null;
}) {
  const qc = useQueryClient();
  const [taskId, setTaskId] = useState<number | undefined>(preselectedTaskId ?? worklog?.task?.id);

  const tasksQ = useQuery({
    queryKey: ["tasks-lite", projectId],
    queryFn: () => listTasks({ projectId, pageSize: 500 }),
    enabled: open,
  });

  const form = useForm<CreateFields>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      workDate: new Date().toISOString().slice(0, 10),
      hours: 1,
      description: "",
    },
  });

  useEffect(() => {
    if (worklog) {
      form.reset({
        workDate: worklog.workDate.slice(0, 10),
        hours: Number(worklog.hours),
        description: worklog.description ?? "",
      });
      setTaskId(worklog.task?.id);
    } else if (open) {
      form.reset({ workDate: new Date().toISOString().slice(0, 10), hours: 1, description: "" });
      setTaskId(preselectedTaskId);
    }
  }, [worklog, open]);

  const save = useMutation({
    mutationFn: async (v: CreateFields) => {
      if (worklog) {
        return updateWorklog(worklog.id, v as WorklogUpdateInput);
      }
      const input: WorklogCreateInput = { ...v, projectId, taskId };
      return createWorklog(input);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worklogs"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks", { projectId }] });
      toast.success(worklog ? "Đã cập nhật worklog" : "Đã log giờ làm việc");
      onClose();
    },
    onError: (e: any) => {
      toast.error(e.response?.data?.error?.message ?? "Có lỗi xảy ra");
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={worklog ? "Sửa worklog" : "Log giờ làm việc"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        {!worklog && (
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
            <input type="date" className="input" {...form.register("workDate")} />
            {form.formState.errors.workDate && (
              <p className="mt-1 text-xs text-red-600">{form.formState.errors.workDate.message}</p>
            )}
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
            {form.formState.errors.hours && (
              <p className="mt-1 text-xs text-red-600">{form.formState.errors.hours.message}</p>
            )}
          </div>
        </div>

        <div>
          <label className="label">Mô tả</label>
          <textarea rows={3} className="input" {...form.register("description")} />
        </div>

        {save.isError && (
          <p className="text-sm text-red-600">{(save.error as any)?.response?.data?.error?.message ?? "Có lỗi"}</p>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>
            Hủy
          </button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {save.isPending ? "Đang lưu…" : "Lưu"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
