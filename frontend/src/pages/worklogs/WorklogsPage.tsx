import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Plus, Pencil, Trash2, Search, X } from "lucide-react";
import { Link } from "react-router-dom";
import { deleteWorklog, listWorklogs, type Worklog } from "@/features/worklogs/api";
import { listProjects } from "@/features/projects/api";
import { formatDate, formatHours } from "@/lib/format";
import { useAuth } from "@/features/auth/store";
import { WorklogFormModal } from "./WorklogFormModal";
import { toast } from "sonner";

type Mode = "mine" | "all";

export function WorklogsPage() {
  const user = useAuth((s) => s.user)!;
  const isAdmin = user.role === "ADMIN" || user.isSuperAdmin;
  const [mode, setMode] = useState<Mode>("mine");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Worklog | null>(null);
  const [createProjectId, setCreateProjectId] = useState<number | undefined>();
  const qc = useQueryClient();

  const params = mode === "mine" ? { mine: true, limit: 500 } : { limit: 500 };

  const listQ = useQuery({
    queryKey: ["worklogs", { mode }],
    queryFn: () => listWorklogs(params),
  });

  const projectsQ = useQuery({
    queryKey: ["projects-lite"],
    queryFn: () => listProjects({ pageSize: 500 }),
    enabled: creating && !createProjectId,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["worklogs"] });

  const del = useMutation({
    mutationFn: deleteWorklog,
    onSuccess: () => { toast.success("Đã xóa worklog"); invalidate(); },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  // Lọc client-side trên worklog đã tải (tối đa 500).
  const [q, setQ] = useState("");
  const [projectFilter, setProjectFilter] = useState<"" | number>("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const all = listQ.data?.data ?? [];

  const projectOptions = useMemo(() => {
    const m = new Map<number, string>();
    all.forEach((w) => m.set(w.project.id, w.project.name));
    return [...m].map(([id, name]) => ({ id, name }));
  }, [all]);

  const items = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return all.filter((w) => {
      if (kw && !(w.task?.name?.toLowerCase().includes(kw) || w.description?.toLowerCase().includes(kw))) return false;
      if (projectFilter !== "" && w.project.id !== projectFilter) return false;
      if (from && w.workDate.slice(0, 10) < from) return false;
      if (to && w.workDate.slice(0, 10) > to) return false;
      return true;
    });
  }, [all, q, projectFilter, from, to]);

  const totalHours = items.reduce((s, w) => s + Number(w.hours), 0);
  const hasFilter = q || projectFilter !== "" || from || to;

  const handleStartCreate = () => {
    setCreateProjectId(undefined);
    setCreating(true);
  };

  const handleCloseCreate = () => {
    setCreating(false);
    setCreateProjectId(undefined);
  };

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">Nhật ký công việc</h1>
          <p className="text-sm text-slate-500">Ghi nhận giờ làm việc theo dự án</p>
        </div>
        <button className="btn-primary" onClick={handleStartCreate}>
          <Plus className="mr-1 h-4 w-4" /> Log giờ
        </button>
      </div>

      <div className="flex gap-2">
        <ModeButton active={mode === "mine"} onClick={() => setMode("mine")}>
          Của tôi
        </ModeButton>
        {isAdmin && (
          <ModeButton active={mode === "all"} onClick={() => setMode("all")}>
            Tất cả
          </ModeButton>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            className="input w-56 pl-8"
            placeholder="Tìm task / mô tả…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {projectOptions.length > 1 && (
          <select
            className="input w-52"
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">Mọi dự án</option>
            {projectOptions.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
        <div className="flex items-center gap-1 text-sm text-slate-500">
          <span>Ngày</span>
          <input type="date" className="input w-36" value={from} onChange={(e) => setFrom(e.target.value)} title="Từ ngày" />
          <span>→</span>
          <input type="date" className="input w-36" value={to} onChange={(e) => setTo(e.target.value)} title="Đến ngày" />
        </div>
        {hasFilter && (
          <button
            className="btn-secondary flex items-center gap-1 text-sm"
            onClick={() => { setQ(""); setProjectFilter(""); setFrom(""); setTo(""); }}
          >
            <X className="h-4 w-4" /> Xóa lọc
          </button>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Kpi label="Số worklog" value={items.length} />
        <Kpi label="Tổng giờ" value={formatHours(totalHours)} />
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Ngày</th>
              <th className="p-3">Dự án</th>
              <th className="p-3">Task</th>
              <th className="p-3">Giờ</th>
              {mode === "all" && <th className="p-3">Người log</th>}
              <th className="p-3">Mô tả</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {listQ.isLoading && (
              <tr>
                <td colSpan={mode === "all" ? 7 : 6} className="p-6 text-center text-sm text-slate-500">
                  Đang tải…
                </td>
              </tr>
            )}
            {items.map((w) => {
              const isOwner = w.userId === user.id;
              const canEdit = isAdmin || isOwner;
              const canDelete = isAdmin || isOwner;

              return (
                <tr
                  key={w.id}
                  className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50 align-top"
                >
                  <td className="p-3 whitespace-nowrap">{formatDate(w.workDate)}</td>
                  <td className="p-3">
                    <Link
                      to={`/projects/${w.project.id}?tab=worklogs`}
                      className="text-brand-700 hover:underline"
                    >
                      {w.project.name}
                    </Link>
                  </td>
                  <td className="p-3">{w.task?.name ?? "—"}</td>
                  <td className="p-3 font-medium">{formatHours(Number(w.hours))}</td>
                  {mode === "all" && <td className="p-3 text-slate-500">{w.user.fullName}</td>}
                  <td className="p-3 max-w-xs text-slate-600">{w.description ?? "—"}</td>
                  <td className="p-3 text-right">
                    <div className="flex justify-end gap-1">
                      {canEdit && (
                        <button
                          className="rounded p-1 hover:bg-slate-100"
                          onClick={() => setEditing(w)}
                          title="Sửa"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {canDelete && (
                        <button
                          className="rounded p-1 text-red-600 hover:bg-red-50"
                          onClick={() => confirm("Xóa worklog này?") && del.mutate(w.id)}
                          title="Xóa"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {!listQ.isLoading && items.length === 0 && (
              <tr>
                <td colSpan={mode === "all" ? 7 : 6} className="p-6 text-center text-slate-500">
                  {all.length === 0 ? "Trống" : "Không có worklog khớp bộ lọc."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Project picker before opening the create form */}
      {creating && !createProjectId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="card w-80 space-y-3 p-6">
            <h2 className="font-semibold">Chọn dự án</h2>
            <select
              className="input"
              defaultValue=""
              onChange={(e) => e.target.value && setCreateProjectId(Number(e.target.value))}
            >
              <option value="">— Chọn dự án —</option>
              {(projectsQ.data?.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <div className="flex justify-end">
              <button className="btn-ghost border border-slate-200" onClick={handleCloseCreate}>
                Hủy
              </button>
            </div>
          </div>
        </div>
      )}

      {creating && createProjectId && (
        <WorklogFormModal
          open={true}
          onClose={handleCloseCreate}
          projectId={createProjectId}
        />
      )}

      {editing && (
        <WorklogFormModal
          open={true}
          onClose={() => setEditing(null)}
          projectId={editing.projectId}
          worklog={editing}
        />
      )}
    </div>
  );
}

function ModeButton({ children, active, onClick }: { children: React.ReactNode; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-4 py-2 text-sm font-medium ${
        active ? "bg-brand-600 text-white" : "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50"
      }`}
    >
      {children}
    </button>
  );
}

function Kpi({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="card">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}
