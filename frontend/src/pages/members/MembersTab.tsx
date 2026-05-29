import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { memberCreateSchema, type MemberCreateInput } from "@bb-pm/shared";
import {
  createMember,
  deleteMember,
  listMembers,
  updateMember,
  type Member,
} from "@/features/members/api";
import { listUsers } from "@/features/users/api";
import { Modal } from "@/components/ui/Modal";
import { formatDate } from "@/lib/format";
import { useAuth } from "@/features/auth/store";

export function MembersTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const canEdit = user?.role === "ADMIN" || user?.role === "MANAGER" || user?.isSuperAdmin;

  const { data: members = [], isLoading } = useQuery({
    queryKey: ["members", projectId],
    queryFn: () => listMembers(projectId),
  });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Member | null>(null);

  const del = useMutation({
    mutationFn: deleteMember,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["members", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{members.length} thành viên</p>
        {canEdit && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus className="mr-1 h-4 w-4" /> Thêm thành viên
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải…</p>
      ) : members.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Chưa có thành viên</div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
              <tr>
                <th className="p-3">Thành viên</th>
                <th className="p-3">Email</th>
                <th className="p-3">Vai trò dự án</th>
                <th className="p-3">Tham gia</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => {
                return (
                  <tr key={m.id} className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                    <td className="p-3 font-medium">{m.user.fullName}</td>
                    <td className="p-3 text-slate-500">{m.user.email}</td>
                    <td className="p-3">{m.role ?? "—"}</td>
                    <td className="p-3 text-slate-500">{formatDate(m.joinedAt)}</td>
                    <td className="p-3 text-right">
                      <div className="flex justify-end gap-1">
                        {canEdit && (
                          <>
                            <button className="rounded p-1 hover:bg-slate-100" onClick={() => setEditing(m)}>
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              className="rounded p-1 text-red-600 hover:bg-red-50"
                              onClick={() => confirm(`Xóa thành viên ${m.user.fullName}?`) && del.mutate(m.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <MemberFormModal open={creating} onClose={() => setCreating(false)} projectId={projectId} existingMemberUserIds={members.map(m => m.userId)} />
      <MemberFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        projectId={projectId}
        member={editing}
        existingMemberUserIds={members.map(m => m.userId)}
      />
    </div>
  );
}

function MemberFormModal({
  open,
  onClose,
  projectId,
  member,
  existingMemberUserIds,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  member?: Member | null;
  existingMemberUserIds: number[];
}) {
  const qc = useQueryClient();
  const usersQ = useQuery({ queryKey: ["users"], queryFn: listUsers, enabled: open });

  const form = useForm<MemberCreateInput>({
    resolver: zodResolver(memberCreateSchema),
    values: member ? { userId: member.userId, role: member.role ?? undefined } : undefined,
  });

  const save = useMutation({
    mutationFn: async (v: MemberCreateInput) =>
      member ? updateMember(member.id, { role: v.role }) : createMember(projectId, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["members", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={member ? "Sửa thành viên" : "Thêm thành viên"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        <div>
          <label className="label">Người dùng *</label>
          <select
            className="input"
            disabled={!!member}
            {...form.register("userId", { valueAsNumber: true })}
          >
            <option value="">— Chọn —</option>
            {usersQ.data?.map((u) => {
              const taken = existingMemberUserIds.includes(u.id) && u.id !== member?.userId;
              return (
                <option key={u.id} value={u.id} disabled={taken}>
                  {u.fullName} ({u.email}) {taken ? "· đã thêm" : ""}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label className="label">Vai trò trong dự án</label>
          <input className="input" placeholder="PM / Dev / QA…" {...form.register("role")} />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>Lưu</button>
        </div>
      </form>
    </Modal>
  );
}
