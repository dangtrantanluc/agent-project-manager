import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  useDraggable,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { listTasks, updateTask, deleteTask, type TaskListItem } from "@/features/tasks/api";
import type { TaskStatus } from "@bb-pm/shared";
import { Badge } from "@/components/ui/Badge";
import { StatusSelect } from "@/components/ui/StatusSelect";
import { TagChips } from "@/components/ui/TagChips";
import { TagMultiSelect } from "@/components/ui/TagMultiSelect";
import { statusColors, statusLabels, priorityColors, formatDate, deadlineState, deadlineTextClass, deadlineRowClass } from "@/lib/format";
import { Pencil, Trash2, Plus, Upload, List, LayoutGrid, Search, X } from "lucide-react";
import { TaskFormModal } from "./TaskFormModal";
import { ImportTasksModal } from "@/pages/projects/ImportTasksModal";
import { useAuth } from "@/features/auth/store";

const COLUMNS: TaskStatus[] = ["TODO", "IN_PROGRESS", "DONE", "CANCELLED"];

export function TaskKanbanBoard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const canEdit =
    user?.role === "ADMIN" || user?.role === "MANAGER" || user?.role === "MEMBER" || user?.isSuperAdmin;

  const tasksQ = useQuery({
    queryKey: ["tasks", { projectId }],
    queryFn: () => listTasks({ projectId, pageSize: 500 }),
  });

  const [view, setView] = useState<"list" | "kanban">("list");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<TaskListItem | null>(null);
  const [importing, setImporting] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  // Bộ lọc client-side (đã fetch tối đa 500 task của project nên lọc tại chỗ là đủ nhanh).
  const [filters, setFilters] = useState({
    q: "",
    status: "" as "" | TaskStatus,
    priority: "",
    assigneeId: "" as "" | number,
    milestoneId: "" as "" | number,
    from: "",
    to: "",
    tagIds: [] as number[],
  });

  const all = tasksQ.data?.data ?? [];

  // Danh sách assignee/milestone duy nhất để đổ vào dropdown (rút từ chính các task hiện có).
  const { assignees, milestones } = useMemo(() => {
    const aMap = new Map<number, string>();
    const mMap = new Map<number, string>();
    all.forEach((t) => {
      if (t.assignee) aMap.set(t.assignee.id, t.assignee.fullName);
      if (t.milestone) mMap.set(t.milestone.id, t.milestone.name);
    });
    return {
      assignees: [...aMap].map(([id, name]) => ({ id, name })),
      milestones: [...mMap].map(([id, name]) => ({ id, name })),
    };
  }, [all]);

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return all.filter((t) => {
      if (q && !t.name.toLowerCase().includes(q)) return false;
      if (filters.status && t.status !== filters.status) return false;
      if (filters.priority && t.priority !== filters.priority) return false;
      if (filters.assigneeId !== "" && t.assignee?.id !== filters.assigneeId) return false;
      if (filters.milestoneId !== "" && t.milestone?.id !== filters.milestoneId) return false;
      if (filters.from && (!t.deadline || t.deadline.slice(0, 10) < filters.from)) return false;
      if (filters.to && (!t.deadline || t.deadline.slice(0, 10) > filters.to)) return false;
      // Lọc đa nhãn (OR): khớp nếu task có ÍT NHẤT 1 nhãn được chọn.
      if (filters.tagIds.length && !t.tags?.some((tg) => filters.tagIds.includes(tg.id))) return false;
      return true;
    });
  }, [all, filters]);

  const byStatus = useMemo(() => {
    const m: Record<TaskStatus, TaskListItem[]> = {
      TODO: [],
      IN_PROGRESS: [],
      DONE: [],
      CANCELLED: [],
    };
    filtered.forEach((t) => {
      if (t.status in m) m[t.status].push(t);
    });
    return m;
  }, [filtered]);

  const transition = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TaskStatus }) => updateTask(id, { status }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ["tasks", { projectId }] });
      const prev = qc.getQueryData<any>(["tasks", { projectId }]);
      if (prev) {
        qc.setQueryData(["tasks", { projectId }], {
          ...prev,
          data: prev.data.map((t: TaskListItem) => (t.id === id ? { ...t, status } : t)),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(["tasks", { projectId }], ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: ["tasks", { projectId }] }),
  });

  const del = useMutation({
    mutationFn: deleteTask,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", { projectId }] }),
  });

  const handleDragStart = (e: DragStartEvent) => setActiveId(Number(e.active.id));
  const handleDragEnd = (e: DragEndEvent) => {
    setActiveId(null);
    if (!canEdit) return;
    if (!e.over) return;
    const taskId = Number(e.active.id);
    const toStatus = String(e.over.id) as TaskStatus;
    const task = tasksQ.data?.data.find((t) => t.id === taskId);
    if (!task || task.status === toStatus) return;
    transition.mutate({ id: taskId, status: toStatus });
  };

  const activeTask = tasksQ.data?.data.find((t) => t.id === activeId);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {filtered.length === all.length
            ? `${all.length} task`
            : `${filtered.length} / ${all.length} task`}
          {view === "kanban" ? " — kéo thả giữa các cột để chuyển trạng thái" : ""}
        </p>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
            <button
              className={`p-2 ${view === "list" ? "bg-slate-100 dark:bg-slate-700" : ""}`}
              onClick={() => setView("list")}
              title="Danh sách"
            >
              <List className="h-4 w-4" />
            </button>
            <button
              className={`p-2 ${view === "kanban" ? "bg-slate-100 dark:bg-slate-700" : ""}`}
              onClick={() => setView("kanban")}
              title="Kanban"
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
          </div>
          {canEdit && (
            <>
              <button
                className="btn-secondary flex items-center gap-1 text-sm"
                onClick={() => setImporting(true)}
              >
                <Upload className="h-4 w-4" /> Import Excel
              </button>
              <button className="btn-primary" onClick={() => setCreating(true)}>
                <Plus className="mr-1 h-4 w-4" /> Tạo task
              </button>
            </>
          )}
        </div>
      </div>

      <TaskFilterBar
        filters={filters}
        setFilters={setFilters}
        assignees={assignees}
        milestones={milestones}
      />

      {view === "kanban" ? (
        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="grid gap-3 md:grid-cols-3">
            {COLUMNS.map((status) => (
              <Column
                key={status}
                status={status}
                items={byStatus[status]}
                canEdit={!!canEdit}
                allowedFrom={activeTask?.status}
                onEdit={(t) => setEditing(t)}
                onDelete={(t) => confirm(`Xóa "${t.name}"?`) && del.mutate(t.id)}
              />
            ))}
          </div>
          <DragOverlay>
            {activeTask && <TaskCard task={activeTask} canEdit={false} onEdit={() => {}} onDelete={() => {}} />}
          </DragOverlay>
        </DndContext>
      ) : (
        <TaskListView
          tasks={filtered}
          loading={tasksQ.isLoading}
          canEdit={!!canEdit}
          onEdit={(t) => setEditing(t)}
          onDelete={(t) => confirm(`Xóa "${t.name}"?`) && del.mutate(t.id)}
          onChangeStatus={(t, status) => transition.mutate({ id: t.id, status })}
        />
      )}

      <TaskFormModal open={creating} onClose={() => setCreating(false)} projectId={projectId} />
      <TaskFormModal open={!!editing} onClose={() => setEditing(null)} projectId={projectId} task={editing} />
      <ImportTasksModal
        open={importing}
        onClose={() => setImporting(false)}
        projectId={projectId}
        onSuccess={() => qc.invalidateQueries({ queryKey: ["tasks", { projectId }] })}
      />
    </div>
  );
}

type TaskFilters = {
  q: string;
  status: "" | TaskStatus;
  priority: string;
  assigneeId: "" | number;
  milestoneId: "" | number;
  from: string;
  to: string;
  tagIds: number[];
};

function TaskFilterBar({
  filters,
  setFilters,
  assignees,
  milestones,
}: {
  filters: TaskFilters;
  setFilters: React.Dispatch<React.SetStateAction<TaskFilters>>;
  assignees: { id: number; name: string }[];
  milestones: { id: number; name: string }[];
}) {
  const set = (patch: Partial<TaskFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const active =
    filters.q ||
    filters.status ||
    filters.priority ||
    filters.assigneeId !== "" ||
    filters.milestoneId !== "" ||
    filters.from ||
    filters.to ||
    filters.tagIds.length > 0;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          className="input w-56 pl-8"
          placeholder="Tìm tiêu đề…"
          value={filters.q}
          onChange={(e) => set({ q: e.target.value })}
        />
      </div>
      <select className="input w-40" value={filters.status} onChange={(e) => set({ status: e.target.value as any })}>
        <option value="">Tất cả trạng thái</option>
        {(["TODO", "IN_PROGRESS", "DONE", "CANCELLED"] as const).map((s) => (
          <option key={s} value={s}>{statusLabels[s]}</option>
        ))}
      </select>
      <select className="input w-36" value={filters.priority} onChange={(e) => set({ priority: e.target.value })}>
        <option value="">Mọi ưu tiên</option>
        {["URGENT", "HIGH", "MEDIUM", "LOW"].map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>
      {assignees.length > 0 && (
        <select
          className="input w-44"
          value={filters.assigneeId}
          onChange={(e) => set({ assigneeId: e.target.value === "" ? "" : Number(e.target.value) })}
        >
          <option value="">Mọi người nhận</option>
          {assignees.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      )}
      {milestones.length > 0 && (
        <select
          className="input w-48"
          value={filters.milestoneId}
          onChange={(e) => set({ milestoneId: e.target.value === "" ? "" : Number(e.target.value) })}
        >
          <option value="">Mọi milestone</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      )}
      <div className="flex items-center gap-1 text-sm text-slate-500">
        <span>Deadline</span>
        <input
          type="date"
          className="input w-36"
          value={filters.from}
          onChange={(e) => set({ from: e.target.value })}
          title="Từ ngày"
        />
        <span>→</span>
        <input
          type="date"
          className="input w-36"
          value={filters.to}
          onChange={(e) => set({ to: e.target.value })}
          title="Đến ngày"
        />
      </div>
      <div className="w-52"><TagMultiSelect value={filters.tagIds} onChange={(ids) => set({ tagIds: ids })} placeholder="Lọc theo nhãn…" /></div>
      {active && (
        <button
          className="btn-secondary flex items-center gap-1 text-sm"
          onClick={() =>
            setFilters({ q: "", status: "", priority: "", assigneeId: "", milestoneId: "", from: "", to: "", tagIds: [] })
          }
        >
          <X className="h-4 w-4" /> Xóa lọc
        </button>
      )}
    </div>
  );
}

function TaskListView({
  tasks,
  loading,
  canEdit,
  onEdit,
  onDelete,
  onChangeStatus,
}: {
  tasks: TaskListItem[];
  loading: boolean;
  canEdit: boolean;
  onEdit: (t: TaskListItem) => void;
  onDelete: (t: TaskListItem) => void;
  onChangeStatus: (t: TaskListItem, status: TaskStatus) => void;
}) {
  if (loading) {
    return <p className="py-8 text-center text-sm text-slate-500">Đang tải…</p>;
  }
  if (tasks.length === 0) {
    return <p className="py-8 text-center text-sm text-slate-400">Chưa có task nào.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-slate-500 dark:bg-slate-900">
          <tr>
            <th className="px-3 py-2 font-medium">Tiêu đề</th>
            <th className="px-3 py-2 font-medium">Trạng thái</th>
            <th className="px-3 py-2 font-medium">Ưu tiên</th>
            <th className="px-3 py-2 font-medium">Nhãn</th>
            <th className="px-3 py-2 font-medium">Assignee</th>
            <th className="px-3 py-2 font-medium">Milestone</th>
            <th className="px-3 py-2 font-medium">Deadline</th>
            {canEdit && <th className="px-3 py-2" />}
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => {
            const rowDs = deadlineState(t.deadline, t.status);
            // Hàng quá hạn/sắp đến hạn -> tô nền; còn lại giữ hover xám mặc định.
            const rowClass = rowDs === "normal"
              ? "hover:bg-slate-50 dark:hover:bg-slate-900/50"
              : deadlineRowClass[rowDs];
            return (
            <tr
              key={t.id}
              className={`group border-t border-slate-100 dark:border-slate-800 ${rowClass}`}
            >
              <td className="px-3 py-2 font-medium text-slate-900 dark:text-slate-100">{t.name}</td>
              <td className="px-3 py-2">
                {canEdit ? (
                  <StatusSelect value={t.status} onChange={(s) => onChangeStatus(t, s)} />
                ) : (
                  <Badge className={statusColors[t.status]}>{statusLabels[t.status]}</Badge>
                )}
              </td>
              <td className="px-3 py-2">
                <Badge className={priorityColors[t.priority]}>{t.priority}</Badge>
              </td>
              <td className="px-3 py-2"><TagChips tags={t.tags} /></td>
              <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{t.assignee?.fullName ?? "—"}</td>
              <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{t.milestone?.name ?? "—"}</td>
              {(() => {
                const ds = deadlineState(t.deadline, t.status);
                return (
                  <td
                    className={`whitespace-nowrap px-3 py-2 ${deadlineTextClass[ds] || "text-slate-500"}`}
                    title={ds === "overdue" ? "Quá hạn" : ds === "due-soon" ? "Sắp đến hạn" : undefined}
                  >
                    {ds === "overdue" && "⚠ "}
                    {t.deadline ? formatDate(t.deadline) : "—"}
                  </td>
                );
              })()}
              {canEdit && (
                <td className="px-3 py-2 text-right">
                  <div className="flex justify-end opacity-0 group-hover:opacity-100">
                    <button className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-700" onClick={() => onEdit(t)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button className="rounded p-1 text-red-600 hover:bg-red-50" onClick={() => onDelete(t)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              )}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Column({
  status,
  items,
  canEdit,
  allowedFrom,
  onEdit,
  onDelete,
}: {
  status: TaskStatus;
  items: TaskListItem[];
  canEdit: boolean;
  allowedFrom?: TaskStatus;
  onEdit: (t: TaskListItem) => void;
  onDelete: (t: TaskListItem) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  const dropValid = !allowedFrom || allowedFrom !== status;
  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col rounded-lg p-3 transition-colors ${
        isOver
          ? (dropValid ? "bg-brand-50 dark:bg-brand-500/10" : "bg-rose-50 dark:bg-rose-500/10")
          : "bg-slate-100 dark:bg-slate-900"
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <Badge className={statusColors[status]}>{statusLabels[status]}</Badge>
        <span className="text-xs text-slate-500">{items.length}</span>
      </div>
      <div className="flex-1 space-y-2">
        {items.map((t) => (
          <DraggableTaskCard key={t.id} task={t} canEdit={canEdit} onEdit={() => onEdit(t)} onDelete={() => onDelete(t)} />
        ))}
        {items.length === 0 && <p className="mt-2 text-center text-xs text-slate-400">Trống</p>}
      </div>
    </div>
  );
}

function DraggableTaskCard(props: Parameters<typeof TaskCard>[0]) {
  if (!props.canEdit) return <TaskCard {...props} />;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: props.task.id });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} className={isDragging ? "opacity-30" : ""}>
      <TaskCard {...props} />
    </div>
  );
}

function TaskCard({
  task,
  canEdit,
  onEdit,
  onDelete,
}: {
  task: TaskListItem;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="group rounded-md bg-white p-3 shadow-sm dark:bg-slate-800">
      <div className="flex items-start justify-between">
        <p className="flex-1 font-medium text-slate-900 dark:text-slate-100">{task.name}</p>
        {canEdit && (
          <div className="flex opacity-0 group-hover:opacity-100">
            <button
              className="rounded p-1 hover:bg-slate-100"
              onClick={(e) => { e.stopPropagation(); onEdit(); }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <Pencil className="h-3 w-3" />
            </button>
            <button
              className="rounded p-1 text-red-600 hover:bg-red-50"
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
      <TagChips tags={task.tags} className="mt-2" />
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{task.assignee?.fullName ?? "—"}</span>
        <Badge className={priorityColors[task.priority]}>{task.priority}</Badge>
      </div>
      {task.deadline && (() => {
        const ds = deadlineState(task.deadline, task.status);
        return (
          <p className={`mt-1 text-xs ${deadlineTextClass[ds] || "text-slate-400"}`}>
            {ds === "overdue" ? "⚠" : "📅"} {formatDate(task.deadline)}
          </p>
        );
      })()}
      {task.milestone && <p className="mt-0.5 text-xs text-slate-400">🏁 {task.milestone.name}</p>}
    </div>
  );
}
