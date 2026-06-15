import { useMutation, useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { listTasks, updateTask, type TaskListItem } from "@/features/tasks/api";
import { listProjects } from "@/features/projects/api";
import { useAuth } from "@/features/auth/store";
import { Badge } from "@/components/ui/Badge";
import { StatusSelect } from "@/components/ui/StatusSelect";
import { TagChips } from "@/components/ui/TagChips";
import { TagMultiSelect } from "@/components/ui/TagMultiSelect";
import { formatDate, priorityColors, statusColors, statusLabels, deadlineState, deadlineTextClass, deadlineRowClass } from "@/lib/format";
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
  const [tagIds, setTagIds] = useState<number[]>([]);

  const PAGE_SIZE = 50;
  // MỌI bộ lọc đẩy xuống SERVER -> phân trang đúng (tránh tải cứng rồi lọc client,
  // vốn sót dữ liệu + lag khi nhiều task). Tải tăng dần qua "Tải thêm".
  const serverFilters = {
    q: q || undefined,
    status: (status as TaskStatus) || undefined,
    assigneeId: onlyMine ? user?.id : undefined,
    priority: priority || undefined,
    projectId: projectId === "" ? undefined : projectId,
    deadlineFrom: from || undefined,
    deadlineTo: to || undefined,
    tagIds: tagIds.length ? tagIds : undefined,
  };

  const tasksQ = useInfiniteQuery({
    queryKey: ["tasks", serverFilters],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => listTasks({ ...serverFilters, page: pageParam, pageSize: PAGE_SIZE }),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((n, p) => n + p.data.length, 0);
      return loaded < lastPage.meta.total ? allPages.length + 1 : undefined;
    },
  });

  const transition = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) => updateTask(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  const tasks = useMemo(
    () => (tasksQ.data?.pages ?? []).flatMap((p) => p.data),
    [tasksQ.data],
  );
  const total = tasksQ.data?.pages[0]?.meta.total ?? 0;

  // Dropdown dự án: lấy danh sách nhẹ riêng (không suy từ trang task đã tải).
  const projectsQ = useQuery({
    queryKey: ["projects-lite-for-tasks"],
    queryFn: () => listProjects({ pageSize: 500 }),
  });
  const projects = useMemo(
    () => (projectsQ.data?.data ?? []).map((p) => ({ id: p.id, name: p.name })),
    [projectsQ.data],
  );

  const hasExtra = priority || projectId !== "" || from || to || tagIds.length > 0;

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Tasks</h1>
          <p className="text-sm text-slate-500">
            {tasks.length >= total ? `${total} task` : `Đã tải ${tasks.length} / ${total} task`}
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
        <div className="w-56"><TagMultiSelect value={tagIds} onChange={setTagIds} placeholder="Lọc theo nhãn…" /></div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
          Chỉ của tôi
        </label>
        {hasExtra && (
          <button
            className="btn-secondary flex items-center gap-1 text-sm"
            onClick={() => { setPriority(""); setProjectId(""); setFrom(""); setTo(""); setTagIds([]); }}
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
              <th className="p-3">Nhãn</th>
              <th className="p-3">Assignee</th>
              <th className="p-3">Deadline</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => {
              const rowDs = deadlineState(t.deadline, t.status);
              const rowClass = rowDs === "normal"
                ? "hover:bg-slate-50 dark:hover:bg-slate-800/50"
                : deadlineRowClass[rowDs];
              return (
              <tr
                key={t.id}
                className={`cursor-pointer border-b border-slate-100 dark:border-slate-800 ${rowClass}`}
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
                  <div className="flex flex-wrap items-center gap-1.5">
                    {canEdit ? (
                      <StatusSelect value={t.status} onChange={(s) => transition.mutate({ id: t.id, status: s })} />
                    ) : (
                      <Badge className={statusColors[t.status]}>{statusLabels[t.status]}</Badge>
                    )}
                    {t.blockerCount > 0 && (
                      <span title={`${t.blockerCount} vướng mắc chưa gỡ`}>
                        <Badge className="bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
                          ⛔ Đang kẹt{t.blockerCount > 1 ? ` (${t.blockerCount})` : ""}
                        </Badge>
                      </span>
                    )}
                  </div>
                </td>
                <td className="p-3"><Badge className={priorityColors[t.priority]}>{t.priority}</Badge></td>
                <td className="p-3"><TagChips tags={t.tags} /></td>
                <td className="p-3 text-slate-500">{t.assignee?.fullName ?? "—"}</td>
                {(() => {
                  const ds = deadlineState(t.deadline, t.status);
                  return (
                    <td
                      className={`p-3 ${deadlineTextClass[ds] || "text-slate-500"}`}
                      title={ds === "overdue" ? "Quá hạn" : ds === "due-soon" ? "Sắp đến hạn" : undefined}
                    >
                      {ds === "overdue" && "⚠ "}
                      {formatDate(t.deadline)}
                    </td>
                  );
                })()}
              </tr>
              );
            })}
            {tasks.length === 0 && !tasksQ.isLoading && (
              <tr><td colSpan={7} className="p-6 text-center text-sm text-slate-500">Không có task nào.</td></tr>
            )}
            {tasksQ.isLoading && (
              <tr><td colSpan={7} className="p-6 text-center text-sm text-slate-500">Đang tải…</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {tasksQ.hasNextPage && (
        <div className="flex justify-center">
          <button
            className="btn-secondary text-sm"
            disabled={tasksQ.isFetchingNextPage}
            onClick={() => tasksQ.fetchNextPage()}
          >
            {tasksQ.isFetchingNextPage ? "Đang tải…" : `Tải thêm (còn ${total - tasks.length})`}
          </button>
        </div>
      )}

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
