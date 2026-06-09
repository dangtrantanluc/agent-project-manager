import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { listTasks, updateTask, type TaskListItem } from "@/features/tasks/api";
import { useAuth } from "@/features/auth/store";
import { Badge } from "@/components/ui/Badge";
import { StatusSelect } from "@/components/ui/StatusSelect";
import { formatDate, priorityColors, statusColors, statusLabels } from "@/lib/format";
import type { TaskStatus } from "@bb-pm/shared";
import { TaskFormModal } from "./TaskFormModal";

export function TasksPage() {
  const user = useAuth((s) => s.user);
  const qc = useQueryClient();
  const canEdit =
    user?.role === "ADMIN" || user?.role === "MANAGER" || user?.role === "MEMBER" || user?.isSuperAdmin;
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"" | TaskStatus>("");
  const [onlyMine, setOnlyMine] = useState(true);
  const [editing, setEditing] = useState<TaskListItem | null>(null);
  // Lọc thêm phía client trên trang đã tải (q + status + assignee đã lọc ở server).
  const [priority, setPriority] = useState("");
  const [projectId, setProjectId] = useState<"" | number>("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const tasksQ = useQuery({
    queryKey: ["tasks", { q, status, assigneeId: onlyMine ? user?.id : undefined }],
    queryFn: () =>
      listTasks({
        q: q || undefined,
        status: (status as TaskStatus) || undefined,
        assigneeId: onlyMine ? user?.id : undefined,
        pageSize: 200,
      }),
  });

  const transition = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) => updateTask(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  const all = tasksQ.data?.data ?? [];

  const projects = useMemo(() => {
    const m = new Map<number, string>();
    all.forEach((t) => m.set(t.project.id, t.project.name));
    return [...m].map(([id, name]) => ({ id, name }));
  }, [all]);

  const tasks = useMemo(
    () =>
      all.filter((t) => {
        if (priority && t.priority !== priority) return false;
        if (projectId !== "" && t.project.id !== projectId) return false;
        if (from && (!t.deadline || t.deadline.slice(0, 10) < from)) return false;
        if (to && (!t.deadline || t.deadline.slice(0, 10) > to)) return false;
        return true;
      }),
    [all, priority, projectId, from, to],
  );

  const hasExtra = priority || projectId !== "" || from || to;

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Tasks</h1>
          <p className="text-sm text-slate-500">
            {tasks.length === all.length ? `${all.length} task` : `${tasks.length} / ${all.length} task`}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input className="input w-64 pl-8" placeholder="Tìm tiêu đề…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input w-44" value={status} onChange={(e) => setStatus(e.target.value as any)}>
          <option value="">Tất cả trạng thái</option>
          {["TODO", "IN_PROGRESS", "DONE", "CANCELLED"].map((s) => (
            <option key={s} value={s}>{statusLabels[s]}</option>
          ))}
        </select>
        <select className="input w-36" value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">Mọi ưu tiên</option>
          {["URGENT", "HIGH", "MEDIUM", "LOW"].map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        {projects.length > 1 && (
          <select
            className="input w-48"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">Mọi dự án</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
        <div className="flex items-center gap-1 text-sm text-slate-500">
          <span>Deadline</span>
          <input type="date" className="input w-36" value={from} onChange={(e) => setFrom(e.target.value)} title="Từ ngày" />
          <span>→</span>
          <input type="date" className="input w-36" value={to} onChange={(e) => setTo(e.target.value)} title="Đến ngày" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
          Chỉ của tôi
        </label>
        {hasExtra && (
          <button
            className="btn-secondary flex items-center gap-1 text-sm"
            onClick={() => { setPriority(""); setProjectId(""); setFrom(""); setTo(""); }}
          >
            <X className="h-4 w-4" /> Xóa lọc
          </button>
        )}
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Tiêu đề</th>
              <th className="p-3">Dự án</th>
              <th className="p-3">Trạng thái</th>
              <th className="p-3">Ưu tiên</th>
              <th className="p-3">Assignee</th>
              <th className="p-3">Deadline</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr
                key={t.id}
                className="cursor-pointer border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                onClick={() => setEditing(t)}
              >
                <td className="p-3 font-medium">{t.name}</td>
                <td className="p-3">
                  <Link
                    to={`/projects/${t.project.id}?tab=tasks`}
                    className="text-brand-700 hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {t.project.name}
                  </Link>
                </td>
                <td className="p-3">
                  {canEdit ? (
                    <StatusSelect value={t.status} onChange={(s) => transition.mutate({ id: t.id, status: s })} />
                  ) : (
                    <Badge className={statusColors[t.status]}>{statusLabels[t.status]}</Badge>
                  )}
                </td>
                <td className="p-3"><Badge className={priorityColors[t.priority]}>{t.priority}</Badge></td>
                <td className="p-3 text-slate-500">{t.assignee?.fullName ?? "—"}</td>
                <td className="p-3 text-slate-500">{formatDate(t.deadline)}</td>
              </tr>
            ))}
            {tasks.length === 0 && (
              <tr><td colSpan={6} className="p-6 text-center text-sm text-slate-500">Không có task nào.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {editing && (
        <TaskFormModal
          open={!!editing}
          onClose={() => setEditing(null)}
          projectId={editing.project.id}
          task={editing}
        />
      )}
    </div>
  );
}
