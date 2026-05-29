import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Plus, LayoutGrid, List, Search, Pencil, Trash2, MoveRight, Loader2 } from "lucide-react";
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
import type { ProjectStatus } from "@bb-pm/shared";
import { deleteProject, listProjects, updateProject, type ProjectListItem } from "@/features/projects/api";
import { Badge } from "@/components/ui/Badge";
import { formatDate, statusColors, statusLabels, priorityColors } from "@/lib/format";
import { ProjectFormModal } from "./ProjectFormModal";
import { useAuth } from "@/features/auth/store";

const STATUSES: ProjectStatus[] = ["PLANNED", "PENDING", "IN_PROGRESS", "DONE", "CANCELLED"];

type ProjectsResponse = Awaited<ReturnType<typeof listProjects>>;

export function ProjectListPage() {
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<ProjectListItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [statusMenuProjectId, setStatusMenuProjectId] = useState<number | null>(null);
  const [movingProjectId, setMovingProjectId] = useState<number | null>(null);
  const [movingToStatus, setMovingToStatus] = useState<ProjectStatus | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);

  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const canEdit = user?.role === "ADMIN" || user?.role === "MANAGER" || user?.isSuperAdmin;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const projectsQ = useQuery({
    queryKey: ["projects", { q }],
    queryFn: () => listProjects({ q: q || undefined, pageSize: 100 }),
  });

  const del = useMutation({
    mutationFn: (id: number) => deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  const transition = useMutation({
    mutationFn: ({ id, status }: { id: number; status: ProjectStatus }) => updateProject(id, { status }),
    onMutate: async ({ id, status }) => {
      const queryKey = ["projects", { q }];
      setMovingProjectId(id);
      setMovingToStatus(status);
      setStatusMenuProjectId(null);

      await qc.cancelQueries({ queryKey: ["projects"] });
      const prev = qc.getQueryData<ProjectsResponse>(queryKey);
      if (prev) {
        qc.setQueryData<ProjectsResponse>(queryKey, {
          ...prev,
          data: prev.data.map((p) => (p.id === id ? { ...p, status } : p)),
        });
      }
      return { prev, queryKey };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(ctx.queryKey, ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      window.setTimeout(() => {
        setMovingProjectId(null);
        setMovingToStatus(null);
      }, 420);
    },
  });

  const handleDragStart = (e: DragStartEvent) => {
    if (!canEdit) return;
    setActiveProjectId(Number(String(e.active.id).replace("project-", "")));
  };

  const handleDragEnd = (e: DragEndEvent) => {
    setActiveProjectId(null);
    if (!canEdit || !e.over) return;
    const projectId = Number(String(e.active.id).replace("project-", ""));
    const toStatus = String(e.over.id) as ProjectStatus;
    const project = projectsQ.data?.data.find((p) => p.id === projectId);
    if (!project || project.status === toStatus) return;
    transition.mutate({ id: projectId, status: toStatus });
  };

  const activeProject = projectsQ.data?.data.find((p) => p.id === activeProjectId);

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dự án</h1>
          <p className="text-sm text-slate-500">{projectsQ.data?.meta.total ?? 0} dự án</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input w-64 pl-8"
              placeholder="Tìm theo tên/mã…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="flex rounded-md border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
            <button
              className={`p-2 ${view === "kanban" ? "bg-slate-100 dark:bg-slate-700" : ""}`}
              onClick={() => setView("kanban")}
              title="Kanban"
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              className={`p-2 ${view === "table" ? "bg-slate-100 dark:bg-slate-700" : ""}`}
              onClick={() => setView("table")}
              title="Bảng"
            >
              <List className="h-4 w-4" />
            </button>
          </div>
          {canEdit && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              <Plus className="mr-1 h-4 w-4" /> Tạo dự án
            </button>
          )}
        </div>
      </div>

      {projectsQ.isLoading ? (
        <p className="text-sm text-slate-500">Đang tải…</p>
      ) : view === "kanban" ? (
        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="grid gap-4 md:grid-cols-5">
            {STATUSES.map((s) => {
              const items = projectsQ.data?.data.filter((p) => p.status === s) ?? [];
              return (
                <ProjectColumn
                  key={s}
                  status={s}
                  items={items}
                  canEdit={!!canEdit}
                  movingToStatus={movingToStatus}
                  renderProject={(p) => (
                    <DraggableProjectCard
                      key={p.id}
                      project={p}
                      canEdit={!!canEdit}
                      statusOptions={STATUSES.filter((status) => status !== p.status)}
                      statusMenuOpen={statusMenuProjectId === p.id}
                      moving={movingProjectId === p.id}
                      transitionPending={transition.isPending && transition.variables?.id === p.id}
                      pendingStatus={transition.variables?.status}
                      onToggleStatusMenu={() => {
                        if (!canEdit) return;
                        setStatusMenuProjectId((current) => (current === p.id ? null : p.id));
                      }}
                      onTransition={(status) => transition.mutate({ id: p.id, status })}
                      onEdit={() => setEditing(p)}
                      onDelete={() => del.mutate(p.id)}
                    />
                  )}
                />
              );
            })}
          </div>
          <DragOverlay>
            {activeProject && (
              <ProjectCard
                project={activeProject}
                canEdit={false}
                statusOptions={[]}
                statusMenuOpen={false}
                moving={false}
                transitionPending={false}
                onToggleStatusMenu={() => {}}
                onTransition={() => {}}
                onEdit={() => {}}
                onDelete={() => {}}
              />
            )}
          </DragOverlay>
        </DndContext>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 text-left dark:bg-slate-800/50">
              <tr>
                <th className="p-3">Tên</th>
                <th className="p-3">Mã</th>
                <th className="p-3">Khách hàng</th>
                <th className="p-3">Trạng thái</th>
                <th className="p-3">Ưu tiên</th>
                <th className="p-3">Deadline</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {projectsQ.data?.data.map((p) => (
                <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                  <td className="p-3">
                    <Link to={`/projects/${p.id}`} className="font-medium text-brand-700 hover:underline">{p.name}</Link>
                  </td>
                  <td className="p-3 text-slate-500">{p.code ?? "—"}</td>
                  <td className="p-3">{p.customerName ?? "—"}</td>
                  <td className="p-3"><Badge className={statusColors[p.status]}>{statusLabels[p.status]}</Badge></td>
                  <td className="p-3"><Badge className={priorityColors[p.priority]}>{p.priority}</Badge></td>
                  <td className="p-3">{formatDate(p.endDate)}</td>
                  <td className="p-3 text-right">
                    {canEdit && (
                      <div className="flex justify-end gap-1">
                        <button className="rounded p-1 hover:bg-slate-100" onClick={() => setEditing(p)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          className="rounded p-1 text-red-600 hover:bg-red-50"
                          onClick={() => confirm(`Xóa "${p.name}"?`) && del.mutate(p.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ProjectFormModal open={creating} onClose={() => setCreating(false)} />
      <ProjectFormModal open={!!editing} onClose={() => setEditing(null)} project={editing} />
    </div>
  );
}

function ProjectColumn({
  status,
  items,
  canEdit,
  movingToStatus,
  renderProject,
}: {
  status: ProjectStatus;
  items: ProjectListItem[];
  canEdit: boolean;
  movingToStatus: ProjectStatus | null;
  renderProject: (project: ProjectListItem) => ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status, disabled: !canEdit });

  return (
    <div
      ref={setNodeRef}
      className={`min-h-[28rem] rounded-lg bg-slate-100 p-3 transition-colors duration-300 dark:bg-slate-900 ${
        isOver
          ? "bg-brand-50 ring-1 ring-brand-300/70 dark:bg-brand-500/10 dark:ring-brand-400/40"
          : movingToStatus === status
            ? "bg-brand-50 ring-1 ring-brand-300/70 dark:bg-brand-500/10 dark:ring-brand-400/40"
            : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <Badge className={statusColors[status]}>{statusLabels[status]}</Badge>
        <span className="text-xs text-slate-500">{items.length}</span>
      </div>
      <div className="space-y-2">
        {items.map(renderProject)}
        {items.length === 0 && <p className="py-8 text-center text-xs text-slate-400">Trống</p>}
      </div>
    </div>
  );
}

function DraggableProjectCard(props: Parameters<typeof ProjectCard>[0]) {
  if (!props.canEdit) return <ProjectCard {...props} />;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `project-${props.project.id}` });

  return (
    <div ref={setNodeRef} {...attributes} {...listeners} className={isDragging ? "opacity-30" : ""}>
      <ProjectCard {...props} />
    </div>
  );
}

function ProjectCard({
  project,
  canEdit,
  onEdit,
  onDelete,
  onToggleStatusMenu,
  onTransition,
  statusOptions,
  statusMenuOpen,
  moving,
  transitionPending,
  pendingStatus,
}: {
  project: ProjectListItem;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onToggleStatusMenu: () => void;
  onTransition: (status: ProjectStatus) => void;
  statusOptions: ProjectStatus[];
  statusMenuOpen: boolean;
  moving: boolean;
  transitionPending: boolean;
  pendingStatus?: ProjectStatus;
}) {
  const canTransition = canEdit && statusOptions.length > 0;

  return (
    <div
      className={`group rounded-md bg-white p-3 shadow-sm transition duration-300 hover:-translate-y-0.5 hover:shadow-md dark:bg-slate-800 ${
        canTransition ? "cursor-pointer" : ""
      } ${moving ? "animate-project-card-move ring-2 ring-brand-400/40" : ""}`}
      role={canTransition ? "button" : undefined}
      tabIndex={canTransition ? 0 : undefined}
      title={canTransition ? "Chuyển trạng thái dự án" : undefined}
      onClick={() => canTransition && onToggleStatusMenu()}
      onKeyDown={(e) => {
        if (!canTransition) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggleStatusMenu();
        }
      }}
    >
      <div className="flex items-start justify-between">
        <Link
          to={`/projects/${project.id}`}
          className="flex-1 font-medium text-slate-900 hover:text-brand-700 dark:text-slate-100 dark:hover:text-brand-400"
          onClick={(e) => e.stopPropagation()}
        >
          {project.name}
        </Link>
        {canEdit && (
          <div className="flex opacity-0 transition-opacity group-hover:opacity-100">
            {canTransition && (
              <button
                className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-brand-700 dark:hover:bg-slate-700"
                title="Chuyển trạng thái"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleStatusMenu();
                }}
              >
                {transitionPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <MoveRight className="h-3 w-3" />}
              </button>
            )}
            <button
              className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-700"
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
            >
              <Pencil className="h-3 w-3" />
            </button>
            <button
              className="rounded p-1 text-red-600 hover:bg-red-50"
              onClick={(e) => {
                e.stopPropagation();
                confirm(`Xóa "${project.name}"?`) && onDelete();
              }}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
      {project.code && <p className="mt-0.5 text-xs text-slate-400">{project.code}</p>}
      {project.customerName && <p className="mt-1 text-xs text-slate-500">👤 {project.customerName}</p>}
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{formatDate(project.endDate)}</span>
        <Badge className={priorityColors[project.priority]}>{project.priority}</Badge>
      </div>
      {canTransition && statusMenuOpen && (
        <div
          className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2 shadow-sm dark:border-slate-700 dark:bg-slate-900/70"
          onClick={(e) => e.stopPropagation()}
        >
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">Chuyển trạng thái</p>
          <div className="flex flex-wrap gap-1.5">
            {statusOptions.map((status) => (
              <button
                key={status}
                className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition hover:scale-[1.02] disabled:cursor-wait disabled:opacity-70 ${statusColors[status]}`}
                disabled={transitionPending}
                onClick={() => onTransition(status)}
              >
                {transitionPending && pendingStatus === status ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <MoveRight className="h-3 w-3" />
                )}
                {statusLabels[status]}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
