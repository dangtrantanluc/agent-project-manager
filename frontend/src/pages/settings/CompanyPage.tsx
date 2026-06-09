import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCompany, updateCompany } from "@/features/admin/api";
import { Building2, Pencil, Check, X } from "lucide-react";
import { toast } from "sonner";

export function CompanyPage() {
  const qc = useQueryClient();
  const companyQ = useQuery({ queryKey: ["company"], queryFn: fetchCompany });

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");

  const save = useMutation({
    mutationFn: (newName: string) => updateCompany({ name: newName }),
    onSuccess: () => {
      toast.success("Đã cập nhật tên công ty");
      qc.invalidateQueries({ queryKey: ["company"] });
      setEditing(false);
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  if (companyQ.isLoading) return <p className="text-sm text-slate-500">Đang tải…</p>;
  if (companyQ.isError || !companyQ.data)
    return <p className="text-sm text-rose-600">Không tải được thông tin công ty. Vui lòng thử lại.</p>;
  const c = companyQ.data;

  const startEdit = () => {
    setName(c.name);
    setEditing(true);
  };

  return (
    <div className="max-w-xl">
      <div className="card space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-brand-100 text-brand-700">
            <Building2 className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs uppercase tracking-wide text-slate-400">Công ty</p>
            {editing ? (
              <div className="mt-1 flex items-center gap-2">
                <input
                  className="input flex-1"
                  value={name}
                  autoFocus
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && name.trim()) save.mutate(name.trim());
                    if (e.key === "Escape") setEditing(false);
                  }}
                />
                <button
                  className="rounded p-1.5 hover:bg-slate-100 disabled:opacity-50"
                  title="Lưu"
                  disabled={!name.trim() || save.isPending}
                  onClick={() => save.mutate(name.trim())}
                >
                  <Check className="h-4 w-4 text-emerald-600" />
                </button>
                <button
                  className="rounded p-1.5 hover:bg-slate-100"
                  title="Hủy"
                  onClick={() => setEditing(false)}
                >
                  <X className="h-4 w-4 text-slate-500" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <h2 className="truncate text-xl font-semibold">{c.name}</h2>
                <button
                  className="rounded p-1.5 hover:bg-slate-100"
                  title="Sửa tên công ty"
                  onClick={startEdit}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 text-sm dark:border-slate-800">
          <Info label="Thành viên" value={c._count.users} />
          <Info label="Dự án" value={c._count.projects} />
        </dl>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
