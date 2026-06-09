import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Search, Check, ChevronDown, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
import { listUsers, type UserOption } from "@/features/users/api";
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
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  const roles = useMemo(
    () => [...new Set(members.map((m) => m.role).filter((r): r is string => !!r))],
    [members],
  );

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return members.filter((m) => {
      if (kw && !(m.user.fullName.toLowerCase().includes(kw) || m.user.email.toLowerCase().includes(kw))) return false;
      if (roleFilter && (m.role ?? "") !== roleFilter) return false;
      return true;
    });
  }, [members, q, roleFilter]);

  const hasFilter = q || roleFilter;

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
        <p className="text-sm text-slate-500">
          {filtered.length === members.length ? `${members.length} thành viên` : `${filtered.length} / ${members.length} thành viên`}
        </p>
        {canEdit && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus className="mr-1 h-4 w-4" /> Thêm thành viên
          </button>
        )}
      </div>

      {members.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input w-56 pl-8"
              placeholder="Tìm tên / email…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {roles.length > 1 && (
            <select className="input w-44" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
              <option value="">Mọi vai trò</option>
              {roles.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          )}
          {hasFilter && (
            <button
              className="btn-secondary flex items-center gap-1 text-sm"
              onClick={() => { setQ(""); setRoleFilter(""); }}
            >
              <X className="h-4 w-4" /> Xóa lọc
            </button>
          )}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải…</p>
      ) : members.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Chưa có thành viên</div>
      ) : filtered.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Không có thành viên khớp bộ lọc.</div>
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
              {filtered.map((m) => {
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

  const selectedUserId = form.watch("userId");

  return (
    <Modal open={open} onClose={onClose} title={member ? "Sửa thành viên" : "Thêm thành viên"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        <div>
          <label className="label">Người dùng *</label>
          <UserPicker
            users={usersQ.data ?? []}
            loading={usersQ.isLoading}
            value={selectedUserId}
            disabled={!!member}
            existingMemberUserIds={existingMemberUserIds}
            currentUserId={member?.userId}
            onChange={(id) =>
              form.setValue("userId", id as number, { shouldValidate: true })
            }
          />
          {form.formState.errors.userId && (
            <p className="mt-1 text-xs text-red-600">Vui lòng chọn người dùng</p>
          )}
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

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function UserPicker({
  users,
  loading,
  value,
  disabled,
  existingMemberUserIds,
  currentUserId,
  onChange,
}: {
  users: UserOption[];
  loading: boolean;
  value?: number;
  disabled?: boolean;
  existingMemberUserIds: number[];
  currentUserId?: number;
  onChange: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = users.find((u) => u.id === value) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = users.filter((u) => {
      const taken = existingMemberUserIds.includes(u.id) && u.id !== currentUserId;
      return !taken;
    });
    if (!q) return base;
    return base.filter(
      (u) =>
        u.fullName.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q),
    );
  }, [users, query, existingMemberUserIds, currentUserId]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  // Focus the search box and reset active item when opening
  useEffect(() => {
    if (open) {
      setActive(0);
      const t = setTimeout(() => inputRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
    setQuery("");
  }, [open]);

  // Keep the highlighted option in view
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.children[active] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function pick(u: UserOption) {
    onChange(u.id);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const u = filtered[active];
      if (u) pick(u);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="input flex items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-60"
      >
        {selected ? (
          <span className="flex min-w-0 items-center gap-2">
            <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-brand-50 text-[10px] font-semibold text-brand-700 dark:bg-brand-700 dark:text-white">
              {initials(selected.fullName)}
            </span>
            <span className="truncate">{selected.fullName}</span>
            <span className="truncate text-slate-400">· {selected.email}</span>
          </span>
        ) : (
          <span className="text-slate-400">— Chọn —</span>
        )}
        <ChevronDown className="h-4 w-4 flex-none text-slate-400" />
      </button>

      {open && !disabled && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <Search className="h-4 w-4 flex-none text-slate-400" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Tìm theo tên hoặc email…"
              className="w-full bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400 dark:text-slate-100"
            />
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  inputRef.current?.focus();
                }}
                className="rounded p-0.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <ul ref={listRef} className="max-h-60 overflow-y-auto py-1">
            {loading ? (
              <li className="px-3 py-2 text-sm text-slate-500">Đang tải…</li>
            ) : filtered.length === 0 ? (
              <li className="px-3 py-2 text-sm text-slate-500">Không tìm thấy người dùng</li>
            ) : (
              filtered.map((u, i) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => pick(u)}
                    onMouseEnter={() => setActive(i)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm ${
                      i === active ? "bg-slate-100 dark:bg-slate-800" : ""
                    }`}
                  >
                    <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700 dark:bg-brand-700 dark:text-white">
                      {initials(u.fullName)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-slate-900 dark:text-slate-100">
                        {u.fullName}
                      </span>
                      <span className="block truncate text-xs text-slate-500">{u.email}</span>
                    </span>
                    {u.id === value && <Check className="h-4 w-4 flex-none text-brand-600" />}
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
