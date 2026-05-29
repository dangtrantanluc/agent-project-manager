import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { meUpdateSchema, type MeUpdateInput } from "@bb-pm/shared";
import { updateMe, uploadAvatar } from "@/features/profile/api";
import { fetchMe } from "@/features/auth/api";
import { useAuth } from "@/features/auth/store";
import { useRef, useState } from "react";
import { Upload, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ProfilePage() {
  const qc = useQueryClient();
  const setStoreUser = useAuth((s) => s.setUser);
  const { i18n } = useTranslation();

  const meQ = useQuery({ queryKey: ["me"], queryFn: fetchMe });

  const form = useForm<MeUpdateInput>({
    resolver: zodResolver(meUpdateSchema),
    values: meQ.data
      ? {
          fullName: meQ.data.fullName,
          avatarUrl: meQ.data.avatarUrl ?? undefined,
          lang: (meQ.data.lang as "vi_VN" | "en_US") ?? "vi_VN",
          timezone: (meQ.data as any).timezone,
        }
      : undefined,
  });

  const [msg, setMsg] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: updateMe,
    onSuccess: async (data) => {
      setMsg("Đã lưu");
      setStoreUser({ ...(useAuth.getState().user as any), ...data });
      if (data.lang) i18n.changeLanguage(data.lang);
      qc.invalidateQueries({ queryKey: ["me"] });
      setTimeout(() => setMsg(null), 2000);
    },
  });

  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: uploadAvatar,
    onSuccess: (url) => {
      form.setValue("avatarUrl", url);
      setStoreUser({ ...(useAuth.getState().user as any), avatarUrl: url });
      qc.invalidateQueries({ queryKey: ["me"] });
      setMsg("Đã upload avatar");
      setTimeout(() => setMsg(null), 2000);
    },
  });

  const currentAvatar = form.watch("avatarUrl") ?? meQ.data?.avatarUrl;

  return (
    <div className="space-y-4 p-6">
      <h1 className="text-2xl font-bold">Hồ sơ</h1>

      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="card max-w-2xl space-y-4">
        <div className="flex items-center gap-4">
          <div className="h-20 w-20 overflow-hidden rounded-full bg-slate-100 ring-2 ring-slate-200">
            {currentAvatar ? (
              <img src={currentAvatar} alt="avatar" className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xl font-bold text-slate-400">
                {meQ.data?.fullName.slice(0, 1).toUpperCase() ?? "?"}
              </div>
            )}
          </div>
          <div>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
              }}
            />
            <button
              type="button"
              className="btn-ghost border border-slate-200"
              onClick={() => fileRef.current?.click()}
              disabled={upload.isPending}
            >
              <Upload className="mr-1 h-4 w-4" />
              {upload.isPending ? "Đang upload…" : "Thay ảnh đại diện"}
            </button>
            <p className="mt-1 text-xs text-slate-500">PNG / JPG / WEBP · Max 2MB</p>
          </div>
        </div>

        <div>
          <label className="label">Họ tên</label>
          <input className="input" {...form.register("fullName")} />
        </div>

        <div>
          <label className="label">URL ảnh đại diện (tùy chọn)</label>
          <input className="input" placeholder="https://..." {...form.register("avatarUrl")} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Ngôn ngữ</label>
            <select className="input" {...form.register("lang")}>
              <option value="vi_VN">Tiếng Việt</option>
              <option value="en_US">English</option>
            </select>
          </div>
          <div>
            <label className="label">Timezone</label>
            <input className="input" {...form.register("timezone")} />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          <div>
            {msg && (
              <span className="inline-flex items-center gap-1 text-sm text-emerald-600">
                <Check className="h-4 w-4" /> {msg}
              </span>
            )}
          </div>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {save.isPending ? "Đang lưu…" : "Lưu"}
          </button>
        </div>
      </form>

      <div className="card max-w-2xl text-sm text-slate-500">
        <p>Email: <span className="font-medium text-slate-700">{meQ.data?.email}</span></p>
        <p>Role: <span className="font-medium text-slate-700">{meQ.data?.role}</span></p>
        <p>Công ty: <span className="font-medium text-slate-700">{(meQ.data as any)?.company?.name}</span></p>
      </div>
    </div>
  );
}
