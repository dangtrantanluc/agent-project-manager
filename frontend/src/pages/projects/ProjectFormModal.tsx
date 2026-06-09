import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectCreateSchema, type ProjectCreateInput, ProjectStatus, Priority } from "@bb-pm/shared";
import { createProject, updateProject, type ProjectListItem } from "@/features/projects/api";
import { listUsers } from "@/features/users/api";
import { Modal } from "@/components/ui/Modal";
import { DateField } from "@/components/ui/DateField";
import { useAuth } from "@/features/auth/store";
import { useEffect } from "react";

export function ProjectFormModal({
  open,
  onClose,
  project,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  project?: ProjectListItem | null;
  onSaved?: () => void;
}) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user)!;

  const usersQ = useQuery({ queryKey: ["users", "options"], queryFn: listUsers });
  const users = usersQ.data ?? [];

  const form = useForm<ProjectCreateInput>({
    resolver: zodResolver(projectCreateSchema),
    defaultValues: { ownerId: user.id, priority: "MEDIUM", status: "PLANNED" },
  });

  // Owner/Account Manager hiện tại có thể trỏ tới id không còn trong danh sách
  // user (vd dữ liệu seed). Giữ id đó như một lựa chọn ẩn để <select> không tự
  // nhảy sang user khác — tránh đánh dấu "dirty" sai và ghi đè owner ngoài ý muốn.
  const currentOwnerId = (project as any)?.ownerId ?? project?.owner?.id ?? null;
  const currentAmId = (project as any)?.accountManagerId ?? null;
  const ownerMissing = currentOwnerId != null && !users.some((u) => u.id === currentOwnerId);
  const amMissing = currentAmId != null && !users.some((u) => u.id === currentAmId);

  useEffect(() => {
    if (project) {
      form.reset({
        name: project.name,
        code: project.code ?? "",
        status: project.status,
        priority: project.priority as any,
        ownerId: currentOwnerId ?? undefined,
        accountManagerId: currentAmId ?? undefined,
        customerName: project.customerName ?? "",
        description: project.description ?? "",
        startDate: project.startDate ?? undefined,
        endDate: project.endDate ?? undefined,
      } as any);
    } else if (open) {
      form.reset({ ownerId: user.id, priority: "MEDIUM", status: "PLANNED" });
    }
  }, [project, open, usersQ.data]);

  // Khi SỬA: chỉ gửi các trường thực sự thay đổi (dirty), giữ nguyên thông tin cũ.
  // Khi TẠO MỚI: gửi toàn bộ form.
  const buildPatch = (v: ProjectCreateInput): Partial<ProjectCreateInput> => {
    const dirty = form.formState.dirtyFields as Record<string, unknown>;
    const patch: Record<string, unknown> = {};
    for (const key of Object.keys(dirty)) {
      patch[key] = (v as Record<string, unknown>)[key];
    }
    return patch as Partial<ProjectCreateInput>;
  };

  const save = useMutation({
    mutationFn: async (v: ProjectCreateInput) =>
      project ? updateProject(project.id, buildPatch(v)) : createProject(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      onSaved?.();
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={project ? "Sửa dự án" : "Tạo dự án"} size="lg">
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="label">Tên dự án *</label>
            <input className="input" {...form.register("name")} />
            {form.formState.errors.name && <p className="mt-1 text-xs text-red-600">{form.formState.errors.name.message}</p>}
          </div>
          <div>
            <label className="label">Mã</label>
            <input className="input" {...form.register("code")} />
          </div>
          <div>
            <label className="label">Khách hàng</label>
            <input className="input" {...form.register("customerName")} />
          </div>
          <div>
            <label className="label">Trạng thái</label>
            <select className="input" {...form.register("status")}>
              {Object.values(ProjectStatus).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Ưu tiên</label>
            <select className="input" {...form.register("priority")}>
              {Object.values(Priority).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Ngày bắt đầu</label>
            <DateField form={form} name="startDate" />
          </div>
          <div>
            <label className="label">Ngày kết thúc</label>
            <DateField form={form} name="endDate" />
          </div>
          <div>
            <label className="label">Owner</label>
            <select className="input" {...form.register("ownerId", { valueAsNumber: true })}>
              {ownerMissing && (
                <option value={currentOwnerId!}>User #{currentOwnerId} (hiện tại)</option>
              )}
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.fullName}</option>
              ))}
            </select>
            {form.formState.errors.ownerId && <p className="mt-1 text-xs text-red-600">Bắt buộc chọn owner</p>}
          </div>
          <div>
            <label className="label">Account Manager</label>
            <select
              className="input"
              {...form.register("accountManagerId", {
                setValueAs: (v) => (v === "" ? undefined : Number(v)),
              })}
            >
              <option value="">—</option>
              {amMissing && (
                <option value={currentAmId!}>User #{currentAmId} (hiện tại)</option>
              )}
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.fullName}</option>
              ))}
            </select>
          </div>
          <div className="col-span-2">
            <label className="label">Mô tả</label>
            <textarea rows={3} className="input" {...form.register("description")} />
          </div>
        </div>

        {save.isError && <p className="text-sm text-red-600">Có lỗi, vui lòng thử lại.</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {save.isPending ? "Đang lưu…" : "Lưu"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
