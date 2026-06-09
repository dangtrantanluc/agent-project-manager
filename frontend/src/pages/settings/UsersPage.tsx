import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { userCreateSchema, type UserCreateInput, Role as RoleEnum } from "@bb-pm/shared";
import {
  createAdminUser,
  listAdminUsers,
  updateAdminUser,
  listGapoMaps,
  createGapoLinkCode,
  unlinkGapoMap,
  type AdminUser,
  type GapoMap,
  type GapoLinkCode,
} from "@/features/admin/api";
import { Plus, Pencil, UserX, UserCheck, Search, Link2, Link2Off, Copy } from "lucide-react";
import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import { formatDate } from "@/lib/format";
import { toast } from "sonner";

const ROLE_COLORS: Record<string, string> = {
  ADMIN: "bg-rose-100 text-rose-700",
  MANAGER: "bg-blue-100 text-blue-700",
  MEMBER: "bg-slate-100 text-slate-700",
  VIEWER: "bg-slate-100 text-slate-500",
};

export function UsersPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);

  const [linkCode, setLinkCode] = useState<{ user: AdminUser; code: GapoLinkCode } | null>(null);

  const usersQ = useQuery({
    queryKey: ["admin-users", q],
    queryFn: () => listAdminUsers({ q: q || undefined }),
  });

  const gapoQ = useQuery({
    queryKey: ["admin-gapo-maps"],
    queryFn: () => listGapoMaps(),
  });
  const gapoByUser = new Map<number, GapoMap>(
    (gapoQ.data ?? []).map((m) => [m.userId, m]),
  );

  const toggleActive = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) => updateAdminUser(id, { active }),
    onSuccess: (u) => {
      toast.success(`${u.active ? "Kích hoạt" : "Vô hiệu hóa"} ${u.fullName}`);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  const genCode = useMutation({
    mutationFn: ({ userId, relink }: { userId: number; relink?: boolean }) =>
      createGapoLinkCode(userId, relink),
    onSuccess: (code, vars) => {
      const user = usersQ.data?.data.find((u) => u.id === vars.userId);
      if (user) setLinkCode({ user, code });
      qc.invalidateQueries({ queryKey: ["admin-gapo-maps"] });
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  const unlink = useMutation({
    mutationFn: (userId: number) => unlinkGapoMap(userId),
    onSuccess: () => {
      toast.success("Đã hủy liên kết Gapo");
      qc.invalidateQueries({ queryKey: ["admin-gapo-maps"] });
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            className="input w-64 pl-8"
            placeholder="Tìm theo tên/email…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus className="mr-1 h-4 w-4" /> Tạo user
        </button>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Họ tên</th>
              <th className="p-3">Email</th>
              <th className="p-3">Vai trò</th>
              <th className="p-3">Trạng thái</th>
              <th className="p-3">Gapo</th>
              <th className="p-3">Đăng nhập cuối</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {usersQ.data?.data.map((u) => (
              <tr key={u.id} className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                <td className="p-3 font-medium">{u.fullName}</td>
                <td className="p-3 text-slate-500">{u.email}</td>
                <td className="p-3"><Badge className={ROLE_COLORS[u.role]}>{u.role}</Badge></td>
                <td className="p-3">
                  {u.active ? (
                    <span className="text-emerald-600">Active</span>
                  ) : (
                    <span className="text-slate-400">Inactive</span>
                  )}
                </td>
                <td className="p-3">
                  {gapoByUser.get(u.id)?.linked ? (
                    <span className="inline-flex items-center gap-1 text-emerald-600" title={gapoByUser.get(u.id)?.gapoFullName ?? undefined}>
                      <Link2 className="h-3.5 w-3.5" /> Đã liên kết
                    </span>
                  ) : (
                    <span className="text-slate-400">Chưa liên kết</span>
                  )}
                </td>
                <td className="p-3 text-slate-500">{u.lastLoginAt ? formatDate(u.lastLoginAt) : "—"}</td>
                <td className="p-3 text-right">
                  <div className="flex justify-end gap-1">
                    <button className="rounded p-1 hover:bg-slate-100" onClick={() => setEditing(u)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    {gapoByUser.get(u.id)?.linked ? (
                      <button
                        className="rounded p-1 hover:bg-slate-100"
                        title="Hủy liên kết Gapo"
                        onClick={() => {
                          if (confirm(`Hủy liên kết Gapo của ${u.fullName}?`)) unlink.mutate(u.id);
                        }}
                      >
                        <Link2Off className="h-3.5 w-3.5 text-rose-600" />
                      </button>
                    ) : (
                      <button
                        className="rounded p-1 hover:bg-slate-100"
                        title="Tạo mã liên kết Gapo"
                        disabled={genCode.isPending}
                        onClick={() => genCode.mutate({ userId: u.id })}
                      >
                        <Link2 className="h-3.5 w-3.5 text-sky-600" />
                      </button>
                    )}
                    <button
                      className="rounded p-1 hover:bg-slate-100"
                      title={u.active ? "Vô hiệu hóa" : "Kích hoạt"}
                      onClick={() => toggleActive.mutate({ id: u.id, active: !u.active })}
                    >
                      {u.active ? <UserX className="h-3.5 w-3.5 text-rose-600" /> : <UserCheck className="h-3.5 w-3.5 text-emerald-600" />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <UserFormModal open={creating} onClose={() => setCreating(false)} />
      <UserFormModal open={!!editing} onClose={() => setEditing(null)} user={editing} />
      <LinkCodeModal data={linkCode} onClose={() => setLinkCode(null)} />
    </div>
  );
}

function LinkCodeModal({
  data,
  onClose,
}: {
  data: { user: AdminUser; code: GapoLinkCode } | null;
  onClose: () => void;
}) {
  const code = data?.code.code ?? "";
  const message =
    `Chào ${data?.user.fullName ?? ""}, để dùng bot PM trên Gapo, hãy nhắn cho bot: ` +
    `/link ${code}\n(Mã hết hạn sau ${data?.code.ttlHours ?? 24} giờ.)`;

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success(`Đã copy ${label}`),
      () => toast.error("Không copy được"),
    );
  };

  return (
    <Modal open={!!data} onClose={onClose} title="Mã liên kết Gapo">
      <div className="space-y-4">
        <p className="text-sm text-slate-500">
          Gửi mã này cho <b>{data?.user.fullName}</b>. Nhân viên nhắn{" "}
          <code className="rounded bg-slate-100 px-1">/link {code}</code> cho bot trên Gapo để hoàn tất liên kết.
        </p>
        <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-4 dark:bg-slate-800/50">
          <span className="font-mono text-2xl tracking-widest">{code}</span>
          <button className="btn-ghost border border-slate-200" onClick={() => copy(code, "mã")}>
            <Copy className="mr-1 h-4 w-4" /> Copy mã
          </button>
        </div>
        <div className="flex justify-between gap-2">
          <button className="btn-ghost border border-slate-200" onClick={() => copy(message, "lời nhắn")}>
            <Copy className="mr-1 h-4 w-4" /> Copy lời nhắn
          </button>
          <button className="btn-primary" onClick={onClose}>Xong</button>
        </div>
      </div>
    </Modal>
  );
}

function UserFormModal({
  open,
  onClose,
  user,
}: {
  open: boolean;
  onClose: () => void;
  user?: AdminUser | null;
}) {
  const qc = useQueryClient();
  const form = useForm<UserCreateInput & { newPassword?: string }>({
    resolver: user ? undefined : zodResolver(userCreateSchema),
    values: user
      ? {
          email: user.email,
          fullName: user.fullName,
          role: user.role,
          password: "",
        } as any
      : undefined,
  });
  const errors = form.formState.errors;

  const save = useMutation({
    mutationFn: async (v: any) => {
      if (user) {
        return updateAdminUser(user.id, {
          fullName: v.fullName,
          role: v.role,
          ...(v.password ? { password: v.password } : {}),
        });
      }
      return createAdminUser(v);
    },
    onSuccess: () => {
      toast.success(user ? "Đã cập nhật" : "Đã tạo user");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  return (
    <Modal open={open} onClose={onClose} title={user ? `Sửa ${user.fullName}` : "Tạo user"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        <div>
          <label className="label">Họ tên *</label>
          <input className="input" {...form.register("fullName")} />
          {errors.fullName && <p className="mt-1 text-xs text-rose-600">{errors.fullName.message}</p>}
        </div>
        <div>
          <label className="label">Email *</label>
          <input className="input" type="email" disabled={!!user} {...form.register("email")} />
          {errors.email && <p className="mt-1 text-xs text-rose-600">{errors.email.message}</p>}
        </div>
        <div>
          <label className="label">Vai trò</label>
          <select className="input" {...form.register("role")}>
            {Object.values(RoleEnum).map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div>
          <label className="label">{user ? "Đặt lại mật khẩu (tùy chọn)" : "Mật khẩu *"}</label>
          <input className="input" type="password" {...form.register("password")} />
          {errors.password && <p className="mt-1 text-xs text-rose-600">{errors.password.message}</p>}
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>Lưu</button>
        </div>
      </form>
    </Modal>
  );
}
