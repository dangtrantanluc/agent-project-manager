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
import { statusColors, statusLabels, priorityColors, formatDate } from "@/lib/format";
import { Pencil, Trash2, Plus, Upload } from "lucide-react";
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

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<TaskListItem | null>(null);
  const [importing, setImporting] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const byStatus = useMemo(() => {
    const m: Record<TaskStatus, TaskListItem[]> = {
      TODO: [],
      IN_PROGRESS: [],
      DONE: [],
      CANCELLED: [],
    };
    tasksQ.data?.data.forEach((t) => {
      if (t.status in m) m[t.status].push(t);
    });
    return m;
  }, [tasksQ.data]);

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
          {tasksQ.data?.meta.total ?? 0} task — kéo thả giữa các cột để chuyển trạng thái
        </p>
        {canEdit && (
          <div className="flex gap-2">
            <button
              className="btn-secondary flex items-center gap-1 text-sm"
              onClick={() => setImporting(true)}
            >
              <Upload className="h-4 w-4" /> Import Excel
            </button>
            <button className="btn-primary" onClick={() => setCreating(true)}>
              <Plus className="mr-1 h-4 w-4" /> Tạo task
            </button>
          </div>
        )}
      </div>

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
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{task.assignee?.fullName ?? "—"}</span>
        <Badge className={priorityColors[task.priority]}>{task.priority}</Badge>
      </div>
      {task.deadline && <p className="mt-1 text-xs text-slate-400">📅 {formatDate(task.deadline)}</p>}
      {task.milestone && <p className="mt-0.5 text-xs text-slate-400">🏁 {task.milestone.name}</p>}
    </div>
  );
}
