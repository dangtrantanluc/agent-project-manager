import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Plus, Pencil, Trash2, Search, X } from "lucide-react";
import { deleteWorklog, listWorklogs, type Worklog } from "@/features/worklogs/api";
import { formatDate, formatHours } from "@/lib/format";
import { useAuth } from "@/features/auth/store";
import { WorklogFormModal } from "./WorklogFormModal";
import { QuickLogRow } from "./QuickLogRow";
import { toast } from "sonner";

export function WorklogsTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user)!;
  const isAdmin = user.role === "ADMIN" || user.isSuperAdmin;

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Worklog | null>(null);

  const listQ = useQuery({
    queryKey: ["worklogs", { projectId }],
    queryFn: () => listWorklogs({ projectId, limit: 500 }),
  });

  // Lọc client-side trên worklog đã tải (tối đa 500).
  const [q, setQ] = useState("");
  const [userId, setUserId] = useState<"" | number>("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const allLogs = listQ.data?.data ?? [];

  const people = useMemo(() => {
    const m = new Map<number, string>();
    allLogs.forEach((w) => m.set(w.user.id, w.user.fullName));
    return [...m].map(([id, name]) => ({ id, name }));
  }, [allLogs]);

  const logs = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return allLogs.filter((w) => {
      if (kw && !(w.task?.name?.toLowerCase().includes(kw) || w.description?.toLowerCase().includes(kw))) return false;
      if (userId !== "" && w.user.id !== userId) return false;
      if (from && w.workDate.slice(0, 10) < from) return false;
      if (to && w.workDate.slice(0, 10) > to) return false;
      return true;
    });
  }, [allLogs, q, userId, from, to]);

  const hasFilter = q || userId !== "" || from || to;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["worklogs"] });
    qc.invalidateQueries({ queryKey: ["project", projectId] });
    qc.invalidateQueries({ queryKey: ["tasks", { projectId }] });
  };

  const del = useMutation({
    mutationFn: deleteWorklog,
    onSuccess: () => { toast.success("Đã xóa worklog"); invalidate(); },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  const totalHours = logs.reduce((s, w) => s + Number(w.hours), 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">
            {logs.length === allLogs.length ? `${allLogs.length} worklog` : `${logs.length} / ${allLogs.length} worklog`}
            {totalHours > 0 && ` · ${formatHours(totalHours)} tổng`}
          </span>
        </div>
        <button className="btn-secondary" onClick={() => setCreating(true)}>
          <Plus className="mr-1 h-4 w-4" /> Log giờ chi tiết
        </button>
      </div>

      {/* Ghi nhanh: task gợi ý sẵn + giờ + Enter, không cần mở modal. */}
      <QuickLogRow projectId={projectId} />

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
        {people.length > 1 && (
          <select
            className="input w-44"
            value={userId}
            onChange={(e) => setUserId(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">Mọi người log</option>
            {people.map((p) => (
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
            onClick={() => { setQ(""); setUserId(""); setFrom(""); setTo(""); }}
          >
            <X className="h-4 w-4" /> Xóa lọc
          </button>
        )}
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Ngày</th>
              <th className="p-3">Task</th>
              <th className="p-3">Giờ</th>
              <th className="p-3">Người log</th>
              <th className="p-3">Mô tả</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {listQ.isLoading && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-sm text-slate-500">Đang tải…</td>
              </tr>
            )}
            {logs.map((w) => {
              const isOwner = w.userId === user.id;
              const canEdit = isAdmin || isOwner;
              const canDelete = isAdmin || isOwner;

              return (
                <tr
                  key={w.id}
                  className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50 align-top"
                >
                  <td className="p-3 whitespace-nowrap">{formatDate(w.workDate)}</td>
                  <td className="p-3">{w.task?.name ?? "—"}</td>
                  <td className="p-3 font-medium">{formatHours(Number(w.hours))}</td>
                  <td className="p-3 text-slate-500">{w.user.fullName}</td>
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
            {!listQ.isLoading && logs.length === 0 && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-sm text-slate-500">
                  {allLogs.length === 0 ? "Chưa có worklog nào." : "Không có worklog khớp bộ lọc."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <WorklogFormModal open={creating} onClose={() => setCreating(false)} projectId={projectId} />
      <WorklogFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        projectId={projectId}
        worklog={editing}
      />
    </div>
  );
}
