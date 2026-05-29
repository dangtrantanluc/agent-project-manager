import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, X, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import type { BacklogStatus } from "@bb-pm/shared";
import {
  approveBacklog,
  listBacklogs,
  rejectBacklog,
  resetBacklog,
} from "@/features/backlogs/api";
import { Badge } from "@/components/ui/Badge";
import { formatDate, formatHours, statusColors, statusLabels } from "@/lib/format";
import { useAuth } from "@/features/auth/store";

type Mode = "queue" | "mine" | "all";

export function BacklogsPage() {
  const user = useAuth((s) => s.user)!;
  const isAdmin = user.role === "ADMIN" || user.isSuperAdmin;
  const [mode, setMode] = useState<Mode>(isAdmin ? "queue" : "mine");
  const qc = useQueryClient();

  const params =
    mode === "queue" ? { status: "PENDING" as BacklogStatus, pageSize: 500 }
    : mode === "mine" ? { mine: true, pageSize: 500 }
    : { pageSize: 500 };

  const listQ = useQuery({
    queryKey: ["backlogs", { mode }],
    queryFn: () => listBacklogs(params),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["backlogs"] });
  const approve = useMutation({ mutationFn: approveBacklog, onSuccess: invalidate });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => rejectBacklog(id, reason),
    onSuccess: invalidate,
  });
  const reset = useMutation({ mutationFn: resetBacklog, onSuccess: invalidate });

  const totalHours = (listQ.data?.data ?? []).reduce((s, b) => s + Number(b.hours), 0);

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold">Nhật ký công việc</h1>
        <p className="text-sm text-slate-500">Log và duyệt giờ làm việc</p>
      </div>

      <div className="flex gap-2">
        {isAdmin && (
          <ModeButton active={mode === "queue"} onClick={() => setMode("queue")}>
            Chờ duyệt
          </ModeButton>
        )}
        <ModeButton active={mode === "mine"} onClick={() => setMode("mine")}>
          Của tôi
        </ModeButton>
        {isAdmin && (
          <ModeButton active={mode === "all"} onClick={() => setMode("all")}>
            Tất cả
          </ModeButton>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Kpi label="Số worklog" value={listQ.data?.meta.total ?? 0} />
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
              <th className="p-3">Người log</th>
              <th className="p-3">Trạng thái</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {listQ.data?.data.map((b) => {
              const isPending = b.status === "PENDING";
              return (
                <tr key={b.id} className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50 align-top">
                  <td className="p-3 whitespace-nowrap">{formatDate(b.workDate)}</td>
                  <td className="p-3">
                    <Link to={`/projects/${b.project.id}?tab=backlogs`} className="text-brand-700 hover:underline">
                      {b.project.name}
                    </Link>
                  </td>
                  <td className="p-3">{b.task?.name ?? "—"}</td>
                  <td className="p-3 font-medium">{formatHours(Number(b.hours))}</td>
                  <td className="p-3 text-slate-500">{b.user.fullName}</td>
                  <td className="p-3">
                    <Badge className={statusColors[b.status]}>{statusLabels[b.status]}</Badge>
                    {b.status === "REJECTED" && b.rejectedReason && (
                      <div className="mt-1 text-xs text-rose-600">{b.rejectedReason}</div>
                    )}
                  </td>
                  <td className="p-3 text-right">
                    {isAdmin && (
                      <div className="flex justify-end gap-1">
                        {isPending ? (
                          <>
                            <button
                              className="rounded p-1 text-emerald-600 hover:bg-emerald-50"
                              onClick={() => approve.mutate(b.id)}
                              title="Duyệt"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                            <button
                              className="rounded p-1 text-rose-600 hover:bg-rose-50"
                              onClick={() => {
                                const reason = prompt("Lý do từ chối?");
                                if (reason) reject.mutate({ id: b.id, reason });
                              }}
                              title="Từ chối"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </>
                        ) : (
                          <button
                            className="rounded p-1 hover:bg-slate-100"
                            onClick={() => reset.mutate(b.id)}
                            title="Reset"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {listQ.data?.data.length === 0 && (
              <tr><td colSpan={8} className="p-6 text-center text-slate-500">Trống</td></tr>
            )}
          </tbody>
        </table>
      </div>
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
