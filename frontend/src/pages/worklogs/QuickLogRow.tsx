import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";

import { createWorklog, type Worklog } from "@/features/worklogs/api";
import { listTaskCandidates } from "@/features/tasks/api";
import { TaskCombobox } from "@/components/ui/TaskCombobox";
import { useAuth } from "@/features/auth/store";

const today = () => new Date().toISOString().slice(0, 10);

/**
 * Dòng "ghi nhanh" worklog ngay trên bảng (không mở modal).
 *
 * Giảm friction so với form modal: task gợi ý sẵn (ưu tiên task của user +
 * deadline gần — từ /tasks/candidates), ngày mặc định hôm nay, Enter để ghi,
 * optimistic update để dòng hiện ngay. Sau khi ghi: giữ task, reset giờ/mô tả
 * + focus lại ô giờ để log task tiếp theo liền tay.
 *
 * Các ca đặc biệt (ngày khác, mô tả dài, sửa) vẫn dùng modal "Log giờ".
 */
export function QuickLogRow({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user)!;

  const [taskId, setTaskId] = useState<number | undefined>(undefined);
  const [touchedTask, setTouchedTask] = useState(false); // user đã tự chọn task chưa
  const [hours, setHours] = useState("");
  const [description, setDescription] = useState("");
  const hoursRef = useRef<HTMLInputElement>(null);

  const candidatesQ = useQuery({
    queryKey: ["task-candidates", projectId],
    queryFn: () => listTaskCandidates({ projectId }),
  });
  const candidates = candidatesQ.data ?? [];
  const taskOptions = useMemo(
    () => candidates.map((c) => ({ id: c.id, name: c.name })),
    [candidates],
  );

  // Auto-chọn gợi ý #1 (task của user + deadline gần nhất) cho tới khi user tự đổi.
  useEffect(() => {
    if (!touchedTask && taskId === undefined && candidates.length > 0) {
      setTaskId(candidates[0].id);
    }
  }, [candidates, taskId, touchedTask]);

  const queryKey = ["worklogs", { projectId }] as const;

  const save = useMutation({
    mutationFn: () =>
      createWorklog({
        projectId,
        workDate: today(),
        hours: Number(hours),
        taskId,
        description: description.trim() || undefined,
      }),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey });
      const prev = qc.getQueryData<{ data: Worklog[]; meta: unknown }>(queryKey);
      const task = candidates.find((c) => c.id === taskId);
      const optimistic: Worklog = {
        id: -Date.now(), // id tạm âm, sẽ bị thay khi invalidate
        workDate: today(),
        hours: Number(hours),
        description: description.trim() || null,
        taskId: taskId ?? null,
        projectId,
        userId: user.id,
        task: task ? { id: task.id, name: task.name } : null,
        project: { id: projectId, name: "" },
        user: { id: user.id, fullName: user.fullName },
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      if (prev) {
        qc.setQueryData(queryKey, { ...prev, data: [optimistic, ...prev.data] });
      }
      return { prev };
    },
    onError: (e: any, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(queryKey, ctx.prev);
      toast.error(e?.response?.data?.error?.message ?? "Ghi worklog thất bại");
    },
    onSuccess: () => {
      toast.success("Đã ghi worklog");
      // Giữ task, reset giờ + mô tả, focus lại ô giờ để log tiếp.
      setHours("");
      setDescription("");
      hoursRef.current?.focus();
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["worklogs"] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks", { projectId }] });
    },
  });

  const hoursNum = Number(hours);
  const valid = hours !== "" && hoursNum >= 0.25 && hoursNum <= 24;

  const submit = () => {
    if (!valid) {
      toast.error("Nhập số giờ hợp lệ (0.25 – 24).");
      hoursRef.current?.focus();
      return;
    }
    save.mutate();
  };

  const onEnter = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="card flex flex-wrap items-end gap-2 p-3">
      <div className="min-w-[16rem] flex-1">
        <label className="label">Task</label>
        <TaskCombobox
          tasks={taskOptions}
          value={taskId}
          onChange={(id) => { setTaskId(id); setTouchedTask(true); }}
          loading={candidatesQ.isLoading}
          placeholder="— Không gắn task —"
        />
      </div>
      <div className="w-24">
        <label className="label">Giờ</label>
        <input
          ref={hoursRef}
          type="number"
          step={0.25}
          min={0.25}
          max={24}
          className="input"
          placeholder="vd 2.5"
          value={hours}
          onChange={(e) => setHours(e.target.value)}
          onKeyDown={onEnter}
        />
      </div>
      <div className="min-w-[12rem] flex-[2]">
        <label className="label">Mô tả</label>
        <input
          className="input"
          placeholder="Bạn đã làm gì?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={onEnter}
        />
      </div>
      <button
        className="btn-primary"
        disabled={!valid || save.isPending}
        onClick={submit}
      >
        <Plus className="mr-1 h-4 w-4" /> {save.isPending ? "Đang ghi…" : "Ghi"}
      </button>
    </div>
  );
}
