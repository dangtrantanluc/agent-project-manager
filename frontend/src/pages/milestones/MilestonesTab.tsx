import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { milestoneCreateSchema, type MilestoneCreateInput } from "@bb-pm/shared";
import {
  createMilestone,
  deleteMilestone,
  listMilestones,
  updateMilestone,
  type Milestone,
} from "@/features/milestones/api";
import { Plus, Pencil, Trash2, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { DateField } from "@/components/ui/DateField";
import { formatDate } from "@/lib/format";
import { useAuth } from "@/features/auth/store";

export function MilestonesTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const canEdit = user?.role === "ADMIN" || user?.role === "MANAGER" || user?.isSuperAdmin;

  const { data: milestones = [], isLoading } = useQuery({
    queryKey: ["milestones", projectId],
    queryFn: () => listMilestones(projectId),
  });
  const [editing, setEditing] = useState<Milestone | null>(null);
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return milestones.filter((m) => {
      if (kw && !m.name.toLowerCase().includes(kw)) return false;
      if (status && (m.status ?? "") !== status) return false;
      return true;
    });
  }, [milestones, q, status]);

  const hasFilter = q || status;

  const del = useMutation({
    mutationFn: deleteMilestone,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["milestones", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {filtered.length === milestones.length ? `${milestones.length} milestone` : `${filtered.length} / ${milestones.length} milestone`}
        </p>
        {canEdit && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus className="mr-1 h-4 w-4" /> Tạo milestone
          </button>
        )}
      </div>

      {milestones.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input w-56 pl-8"
              placeholder="Tìm tên milestone…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select className="input w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Mọi trạng thái</option>
            <option value="planned">planned</option>
            <option value="in_progress">in_progress</option>
            <option value="done">done</option>
          </select>
          {hasFilter && (
            <button
              className="btn-secondary flex items-center gap-1 text-sm"
              onClick={() => { setQ(""); setStatus(""); }}
            >
              <X className="h-4 w-4" /> Xóa lọc
            </button>
          )}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải…</p>
      ) : milestones.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Chưa có milestone nào</div>
      ) : filtered.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Không có milestone khớp bộ lọc.</div>
      ) : (
        <ul className="card divide-y divide-slate-100 p-0">
          {filtered.map((m) => (
            <li key={m.id} className="flex items-center justify-between p-4">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  {m.code && <span className="font-mono text-xs text-slate-400">{m.code}</span>}
                  <p className="font-medium">{m.name}</p>
                  {m.status && <span className="text-xs text-slate-500">({m.status})</span>}
                </div>
                <p className="mt-0.5 text-xs text-slate-500">Hạn {formatDate(m.dueDate)}</p>
                {m.description && <p className="mt-1 text-sm text-slate-600">{m.description}</p>}
              </div>
              <div className="w-48 px-4">
                <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                  <div className="h-full bg-brand-500" style={{ width: `${m.completionPct}%` }} />
                </div>
                <p className="mt-1 text-right text-xs text-slate-500">
                  {m.doneCount}/{m.taskCount} ({m.completionPct}%)
                </p>
              </div>
              {canEdit && (
                <div className="flex gap-1">
                  <button className="rounded p-1 hover:bg-slate-100" onClick={() => setEditing(m)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    className="rounded p-1 text-red-600 hover:bg-red-50"
                    onClick={() => confirm(`Xóa milestone "${m.name}"?`) && del.mutate(m.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <MilestoneFormModal open={creating} onClose={() => setCreating(false)} projectId={projectId} />
      <MilestoneFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        projectId={projectId}
        milestone={editing}
      />
    </div>
  );
}

function MilestoneFormModal({
  open,
  onClose,
  projectId,
  milestone,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  milestone?: Milestone | null;
}) {
  const qc = useQueryClient();
  const form = useForm<MilestoneCreateInput>({
    resolver: zodResolver(milestoneCreateSchema),
    values: milestone
      ? {
          name: milestone.name,
          status: milestone.status ?? undefined,
          dueDate: milestone.dueDate ?? undefined,
          description: milestone.description ?? undefined,
        }
      : undefined,
  });
  const save = useMutation({
    mutationFn: (v: MilestoneCreateInput) =>
      milestone ? updateMilestone(milestone.id, v) : createMilestone(projectId, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["milestones", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={milestone ? "Sửa milestone" : "Tạo milestone"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        <div>
          <label className="label">Tên *</label>
          <input className="input" {...form.register("name")} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Trạng thái</label>
            <select className="input" {...form.register("status")}>
              <option value="">—</option>
              <option value="planned">planned</option>
              <option value="in_progress">in_progress</option>
              <option value="done">done</option>
            </select>
          </div>
          <div>
            <label className="label">Hạn</label>
            <DateField form={form} name="dueDate" />
          </div>
        </div>
        <div>
          <label className="label">Mô tả</label>
          <textarea rows={3} className="input" {...form.register("description")} />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>Lưu</button>
        </div>
      </form>
    </Modal>
  );
}
