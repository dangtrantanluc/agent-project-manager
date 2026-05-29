import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, Pencil, Trash2, Check, X, RotateCcw } from "lucide-react";
import type { BacklogStatus } from "@bb-pm/shared";
import {
  approveBacklog,
  deleteBacklog,
  listBacklogs,
  rejectBacklog,
  resetBacklog,
  type Backlog,
} from "@/features/backlogs/api";
import { Badge } from "@/components/ui/Badge";
import { formatDate, formatHours, statusColors, statusLabels } from "@/lib/format";
import { useAuth } from "@/features/auth/store";
import { BacklogFormModal } from "./BacklogFormModal";
import { toast } from "sonner";

export function BacklogsTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user)!;
  const isAdmin = user.role === "ADMIN" || user.isSuperAdmin;

  const [status, setStatus] = useState<"" | BacklogStatus>("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Backlog | null>(null);

  const listQ = useQuery({
    queryKey: ["backlogs", { projectId, status }],
    queryFn: () =>
      listBacklogs({
        projectId,
        status: (status as BacklogStatus) || undefined,
        pageSize: 500,
      }),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["backlogs"] });
    qc.invalidateQueries({ queryKey: ["project", projectId] });
    qc.invalidateQueries({ queryKey: ["tasks", { projectId }] });
  };

  const approve = useMutation({
    mutationFn: approveBacklog,
    onSuccess: () => { toast.success("Đã duyệt backlog"); invalidate(); },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => rejectBacklog(id, reason),
    onSuccess: () => { toast.success("Đã từ chối"); invalidate(); },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });
  const reset = useMutation({
    mutationFn: resetBacklog,
    onSuccess: () => { toast.success("Đã reset về pending"); invalidate(); },
  });
  const del = useMutation({
    mutationFn: deleteBacklog,
    onSuccess: () => { toast.success("Đã xóa"); invalidate(); },
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <select className="input w-48" value={status} onChange={(e) => setStatus(e.target.value as any)}>
            <option value="">Tất cả trạng thái</option>
            {(["PENDING", "APPROVED", "REJECTED"] as const).map((s) => (
              <option key={s} value={s}>{statusLabels[s]}</option>
            ))}
          </select>
          <span className="text-sm text-slate-500">{listQ.data?.meta.total ?? 0} worklog</span>
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus className="mr-1 h-4 w-4" /> Log giờ
        </button>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Ngày</th>
              <th className="p-3">Task</th>
              <th className="p-3">Giờ</th>
              <th className="p-3">Người log</th>
              <th className="p-3">Trạng thái</th>
              <th className="p-3">Mô tả</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {listQ.data?.data.map((b) => {
              const isOwner = b.user.id === user.id;
              const isPending = b.status === "PENDING";
              const canEdit = isAdmin || (isOwner && isPending);
              const canDelete = canEdit;
              return (
                <tr key={b.id} className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50 align-top">
                  <td className="p-3 whitespace-nowrap">{formatDate(b.workDate)}</td>
                  <td className="p-3">{b.task?.name ?? "—"}</td>
                  <td className="p-3 font-medium">{formatHours(Number(b.hours))}</td>
                  <td className="p-3 text-slate-500">{b.user.fullName}</td>
                  <td className="p-3">
                    <Badge className={statusColors[b.status]}>{statusLabels[b.status]}</Badge>
                    {b.status === "REJECTED" && b.rejectedReason && (
                      <div className="mt-1 text-xs text-rose-600">{b.rejectedReason}</div>
                    )}
                    {b.approver && (
                      <div className="mt-0.5 text-[10px] text-slate-400">Bởi {b.approver.fullName}</div>
                    )}
                  </td>
                  <td className="p-3 max-w-xs text-slate-600">{b.description ?? "—"}</td>
                  <td className="p-3 text-right">
                    <div className="flex justify-end gap-1">
                      {isAdmin && isPending && (
                        <>
                          <button
                            title="Duyệt"
                            className="rounded p-1 text-emerald-600 hover:bg-emerald-50"
                            onClick={() => approve.mutate(b.id)}
                          >
                            <Check className="h-3.5 w-3.5" />
                          </button>
                          <button
                            title="Từ chối"
                            className="rounded p-1 text-rose-600 hover:bg-rose-50"
                            onClick={() => {
                              const reason = prompt("Lý do từ chối?");
                              if (reason) reject.mutate({ id: b.id, reason });
                            }}
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                      {isAdmin && !isPending && (
                        <button
                          title="Reset về PENDING"
                          className="rounded p-1 hover:bg-slate-100"
                          onClick={() => reset.mutate(b.id)}
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {canEdit && (
                        <button className="rounded p-1 hover:bg-slate-100" onClick={() => setEditing(b)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {canDelete && (
                        <button
                          className="rounded p-1 text-red-600 hover:bg-red-50"
                          onClick={() => confirm("Xóa backlog?") && del.mutate(b.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {listQ.data?.data.length === 0 && (
              <tr>
                <td colSpan={8} className="p-6 text-center text-sm text-slate-500">Chưa có worklog nào.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <BacklogFormModal open={creating} onClose={() => setCreating(false)} projectId={projectId} />
      <BacklogFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        projectId={projectId}
        backlog={editing}
      />
    </div>
  );
}
