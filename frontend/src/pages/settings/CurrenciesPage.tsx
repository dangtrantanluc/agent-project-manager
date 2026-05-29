import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { currencyCreateSchema, type CurrencyCreateInput } from "@bb-pm/shared";
import {
  createCurrency,
  deleteCurrency,
  listCurrencies,
  updateCurrency,
  type CurrencyFull,
} from "@/features/admin/api";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { toast } from "sonner";

export function CurrenciesPage() {
  const qc = useQueryClient();
  const currenciesQ = useQuery({ queryKey: ["currencies-admin"], queryFn: listCurrencies });
  const [editing, setEditing] = useState<CurrencyFull | null>(null);
  const [creating, setCreating] = useState(false);

  const del = useMutation({
    mutationFn: deleteCurrency,
    onSuccess: () => {
      toast.success("Đã xóa");
      qc.invalidateQueries({ queryKey: ["currencies-admin"] });
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Không xóa được (đang được sử dụng?)"),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus className="mr-1 h-4 w-4" /> Thêm tiền tệ
        </button>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Mã</th>
              <th className="p-3">Ký hiệu</th>
              <th className="p-3">Tỷ giá</th>
              <th className="p-3">Dùng bởi</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {currenciesQ.data?.map((c) => (
              <tr key={c.id} className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                <td className="p-3 font-mono font-medium">{c.code}</td>
                <td className="p-3">{c.symbol}</td>
                <td className="p-3">{c.rate}</td>
                <td className="p-3 text-slate-500">
                  {c._count?.projects ?? 0} project
                </td>
                <td className="p-3 text-right">
                  <div className="flex justify-end gap-1">
                    <button className="rounded p-1 hover:bg-slate-100" onClick={() => setEditing(c)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      className="rounded p-1 text-red-600 hover:bg-red-50"
                      onClick={() => confirm(`Xóa ${c.code}?`) && del.mutate(c.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CurrencyFormModal open={creating} onClose={() => setCreating(false)} />
      <CurrencyFormModal open={!!editing} onClose={() => setEditing(null)} currency={editing} />
    </div>
  );
}

function CurrencyFormModal({
  open,
  onClose,
  currency,
}: {
  open: boolean;
  onClose: () => void;
  currency?: CurrencyFull | null;
}) {
  const qc = useQueryClient();
  const form = useForm<CurrencyCreateInput>({
    resolver: zodResolver(currencyCreateSchema),
    values: currency
      ? { code: currency.code, symbol: currency.symbol, rate: Number(currency.rate) }
      : undefined,
  });

  const save = useMutation({
    mutationFn: (v: CurrencyCreateInput) =>
      currency ? updateCurrency(currency.id, v) : createCurrency(v),
    onSuccess: () => {
      toast.success(currency ? "Đã cập nhật" : "Đã tạo");
      qc.invalidateQueries({ queryKey: ["currencies-admin"] });
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.error?.message ?? "Thất bại"),
  });

  return (
    <Modal open={open} onClose={onClose} title={currency ? "Sửa tiền tệ" : "Thêm tiền tệ"}>
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Mã (VND, USD…) *</label>
            <input className="input" disabled={!!currency} {...form.register("code")} />
          </div>
          <div>
            <label className="label">Ký hiệu *</label>
            <input className="input" {...form.register("symbol")} />
          </div>
        </div>
        <div>
          <label className="label">Tỷ giá (so với base) *</label>
          <input type="number" step="0.000001" className="input" {...form.register("rate", { valueAsNumber: true })} />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>Lưu</button>
        </div>
      </form>
    </Modal>
  );
}
