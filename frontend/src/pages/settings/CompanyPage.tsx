import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCompany, listCurrencies, updateCompany } from "@/features/admin/api";
import { toast } from "sonner";

export function CompanyPage() {
  const qc = useQueryClient();
  const companyQ = useQuery({ queryKey: ["company"], queryFn: fetchCompany });
  const currenciesQ = useQuery({ queryKey: ["currencies-admin"], queryFn: listCurrencies });

  const form = useForm({
    values: companyQ.data ? {
      name: companyQ.data.name,
      code: companyQ.data.code ?? "",
      currencyId: companyQ.data.currencyId,
    } : undefined,
  });

  const save = useMutation({
    mutationFn: updateCompany,
    onSuccess: () => {
      toast.success("Đã lưu");
      qc.invalidateQueries({ queryKey: ["company"] });
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  if (companyQ.isLoading) return <p className="text-sm text-slate-500">Đang tải…</p>;
  const c = companyQ.data!;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <form onSubmit={form.handleSubmit((v: any) => save.mutate({ ...v, code: v.code || null, currencyId: Number(v.currencyId) }))}
        className="card lg:col-span-2 space-y-4">
        <h2 className="font-semibold">Thông tin công ty</h2>
        <div>
          <label className="label">Tên công ty *</label>
          <input className="input" {...form.register("name", { required: true })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Mã</label>
            <input className="input" {...form.register("code")} />
          </div>
          <div>
            <label className="label">Tiền tệ mặc định</label>
            <select className="input" {...form.register("currencyId")}>
              {currenciesQ.data?.map((cu) => (
                <option key={cu.id} value={cu.id}>{cu.code} ({cu.symbol})</option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex justify-end">
          <button type="submit" className="btn-primary" disabled={save.isPending}>Lưu</button>
        </div>
      </form>

      <div className="card">
        <h2 className="mb-3 font-semibold">Số liệu</h2>
        <dl className="space-y-2 text-sm">
          <Info label="Thành viên" value={c._count.users} />
          <Info label="Dự án" value={c._count.projects} />
          <Info label="Tiền tệ" value={`${c.currency.code} (${c.currency.symbol})`} />
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
