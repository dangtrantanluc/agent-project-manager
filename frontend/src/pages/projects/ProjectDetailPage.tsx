import { useParams, Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProject, transitionProject } from "@/features/projects/api";
import { Badge } from "@/components/ui/Badge";
import { TagChips } from "@/components/ui/TagChips";
import { formatDate, formatHours, statusColors, statusLabels, priorityColors } from "@/lib/format";
import type { ProjectStatus } from "@bb-pm/shared";
import { ArrowLeft, Pencil } from "lucide-react";
import { useState } from "react";
import { TaskKanbanBoard } from "../tasks/TaskKanbanBoard";
import { MilestonesTab } from "../milestones/MilestonesTab";
import { WorklogsTab } from "../worklogs/WorklogsTab";
import { MembersTab as NewMembersTab } from "../members/MembersTab";
import { ScopeTab } from "../scopes/ScopeTab";
import { ProjectFormModal } from "./ProjectFormModal";
import { useAuth } from "@/features/auth/store";

const nextStatuses: Record<ProjectStatus, ProjectStatus[]> = {
  PLANNED: ["PENDING", "IN_PROGRESS", "CANCELLED"],
  PENDING: ["IN_PROGRESS", "CANCELLED"],
  IN_PROGRESS: ["PENDING", "DONE", "CANCELLED"],
  DONE: [],
  CANCELLED: [],
};

const TABS = [
  { id: "overview", label: "Tổng quan" },
  { id: "tasks", label: "Tasks" },
  { id: "milestones", label: "Milestones" },
  { id: "worklogs", label: "Nhật ký công việc" },
  { id: "scope", label: "Scope" },
  { id: "members", label: "Thành viên" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = (searchParams.get("tab") as TabId) ?? "overview";
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const role = useAuth((s) => s.user?.role);
  const isSuperAdmin = useAuth((s) => s.user?.isSuperAdmin);
  const canEdit = isSuperAdmin || role === "MANAGER" || role === "ADMIN";

  const q = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId), enabled: !!projectId });

  const transition = useMutation({
    mutationFn: (status: ProjectStatus) => transitionProject(projectId, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  if (q.isLoading) return <p className="p-6 text-sm text-slate-500">Đang tải…</p>;
  if (!q.data) return <p className="p-6 text-sm text-red-600">Không tìm thấy.</p>;
  const p = q.data;

  return (
    <div className="space-y-4 p-6">
      <div>
        <Link to="/projects" className="mb-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
          <ArrowLeft className="h-3 w-3" /> Quay lại danh sách
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold">{p.name}</h1>
              {p.code && <span className="text-slate-400">#{p.code}</span>}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge className={statusColors[p.status as ProjectStatus]}>{statusLabels[p.status]}</Badge>
              <Badge className={priorityColors[p.priority]}>{p.priority}</Badge>
              <TagChips tags={(p as any).tags ?? []} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {canEdit && (
              <button
                className="btn-ghost border border-slate-200 text-xs"
                onClick={() => setEditing(true)}
              >
                <Pencil className="mr-1 h-3 w-3" /> Sửa
              </button>
            )}
            {nextStatuses[p.status as ProjectStatus].map((s) => (
              <button
                key={s}
                className="btn-ghost border border-slate-200 text-xs"
                onClick={() => transition.mutate(s)}
                disabled={transition.isPending}
              >
                → {statusLabels[s]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {canEdit && (
        <ProjectFormModal
          open={editing}
          onClose={() => setEditing(false)}
          project={p as any}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["project", projectId] });
            qc.invalidateQueries({ queryKey: ["projects"] });
          }}
        />
      )}

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setSearchParams({ tab: t.id })}
              className={`border-b-2 px-4 py-2 text-sm ${
                tab === t.id
                  ? "border-brand-600 font-medium text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {tab === "overview" && <OverviewTab project={p} />}
      {tab === "tasks" && <TaskKanbanBoard projectId={projectId} />}
      {tab === "milestones" && <MilestonesTab projectId={projectId} />}
      {tab === "worklogs" && <WorklogsTab projectId={projectId} />}
      {tab === "scope" && <ScopeTab projectId={projectId} />}
      {tab === "members" && <NewMembersTab projectId={projectId} />}
    </div>
  );
}

function OverviewTab({ project: p }: { project: any }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        <Kpi label="Tasks" value={p._count.tasks} />
        <Kpi label="Worklogs" value={p._count.worklogs ?? p._count.backlogs ?? 0} />
        <Kpi label="Thành viên" value={p._count.members} />
        <Kpi label="Milestones" value={p._count.milestones} />
      </div>

      <div className="card">
        <h2 className="mb-2 font-semibold">Thông tin</h2>
        <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Info label="Owner" value={p.owner?.fullName} />
          <Info label="Account Manager" value={p.accountManager?.fullName ?? "—"} />
          <Info label="Khách hàng" value={p.customerName ?? "—"} />
          <Info label="Bắt đầu" value={formatDate(p.startDate)} />
          <Info label="Kết thúc" value={formatDate(p.endDate)} />
          <Info label="Giờ đã duyệt" value={formatHours(p.totalHours)} />
        </dl>
        {p.description && <p className="mt-4 whitespace-pre-wrap text-sm text-slate-600">{p.description}</p>}
      </div>

      {p.milestones.length > 0 && (
        <div className="card">
          <h2 className="mb-2 font-semibold">Milestones</h2>
          <ul className="divide-y divide-slate-100">
            {p.milestones.map((m: any) => (
              <li key={m.id} className="flex items-center justify-between py-2 text-sm">
                <div>
                  <p className="font-medium">{m.name}</p>
                  <p className="text-xs text-slate-500">Hạn {formatDate(m.dueDate)}</p>
                </div>
                <div className="w-32">
                  <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full bg-brand-500" style={{ width: `${m.completionPct}%` }} />
                  </div>
                  <p className="mt-1 text-right text-xs text-slate-500">{m.doneCount}/{m.taskCount}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="card">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium">{value ?? "—"}</dd>
    </>
  );
}
