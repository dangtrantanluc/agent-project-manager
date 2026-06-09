import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { scopeCreateSchema, type ScopeCreateInput } from "@bb-pm/shared";
import {
  createScope,
  deleteScope,
  listScopes,
  reorderScopes,
  updateScope,
  type Scope,
} from "@/features/scopes/api";
import { Modal } from "@/components/ui/Modal";
import { formatHours } from "@/lib/format";
import { useAuth } from "@/features/auth/store";
import { GripVertical, Plus, Pencil, Trash2, Search, X } from "lucide-react";

export function ScopeTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const canEdit = user?.role === "ADMIN" || user?.role === "MANAGER" || user?.isSuperAdmin;

  const { data: scopes = [], isLoading } = useQuery({
    queryKey: ["scopes", projectId],
    queryFn: () => listScopes(projectId),
  });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Scope | null>(null);
  const [q, setQ] = useState("");

  // Khi đang lọc, tắt kéo-thả sắp xếp (reorder chỉ đúng trên toàn bộ danh sách).
  const filtering = q.trim() !== "";
  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    if (!kw) return scopes;
    return scopes.filter(
      (s) => s.name.toLowerCase().includes(kw) || (s.notes?.toLowerCase().includes(kw) ?? false),
    );
  }, [scopes, q]);

  const reorder = useMutation({
    mutationFn: (ids: number[]) => reorderScopes(projectId, ids),
    onMutate: async (ids) => {
      await qc.cancelQueries({ queryKey: ["scopes", projectId] });
      const prev = qc.getQueryData<Scope[]>(["scopes", projectId]);
      if (prev) {
        const reordered = ids
          .map((id, i) => {
            const s = prev.find((x) => x.id === id);
            return s ? { ...s, sequence: (i + 1) * 10 } : null;
          })
          .filter(Boolean) as Scope[];
        qc.setQueryData(["scopes", projectId], reordered);
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(["scopes", projectId], ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: ["scopes", projectId] }),
  });

  const del = useMutation({
    mutationFn: deleteScope,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scopes", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const ids = scopes.map((s) => s.id);
    const oldIndex = ids.indexOf(Number(e.active.id));
    const newIndex = ids.indexOf(Number(e.over.id));
    reorder.mutate(arrayMove(ids, oldIndex, newIndex));
  };

  const totalEstimatedHours = scopes.reduce((s, x) => s + Number(x.estimatedHours ?? 0), 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-4 text-sm text-slate-500">
          <span>{filtering ? `${filtered.length} / ${scopes.length}` : scopes.length} scope item</span>
          <span>Tổng giờ ước tính: <b className="text-slate-700">{formatHours(totalEstimatedHours)}</b></span>
        </div>
        {canEdit && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus className="mr-1 h-4 w-4" /> Thêm mục
          </button>
        )}
      </div>

      {scopes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input w-56 pl-8"
              placeholder="Tìm tên / ghi chú…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {filtering && (
            <>
              <span className="text-xs text-slate-400">Đang lọc — tắt kéo-thả sắp xếp</span>
              <button className="btn-secondary flex items-center gap-1 text-sm" onClick={() => setQ("")}>
                <X className="h-4 w-4" /> Xóa lọc
              </button>
            </>
          )}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải…</p>
      ) : scopes.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Chưa có mục scope</div>
      ) : filtered.length === 0 ? (
        <div className="card text-center text-sm text-slate-500">Không có mục scope khớp bộ lọc.</div>
      ) : filtering ? (
        <ul className="card divide-y divide-slate-100 p-0">
          {filtered.map((s) => (
            <StaticScopeRow
              key={s.id}
              scope={s}
              canEdit={!!canEdit}
              onEdit={() => setEditing(s)}
              onDelete={() => confirm(`Xóa "${s.name}"?`) && del.mutate(s.id)}
            />
          ))}
        </ul>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={scopes.map((s) => s.id)} strategy={verticalListSortingStrategy}>
            <ul className="card divide-y divide-slate-100 p-0">
              {scopes.map((s) => (
                <SortableScopeRow
                  key={s.id}
                  scope={s}
                  canEdit={!!canEdit}
                  onEdit={() => setEditing(s)}
                  onDelete={() => confirm(`Xóa "${s.name}"?`) && del.mutate(s.id)}
                />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
      )}

      <ScopeFormModal open={creating} onClose={() => setCreating(false)} projectId={projectId} />
      <ScopeFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        projectId={projectId}
        scope={editing}
      />
    </div>
  );
}

function StaticScopeRow({
  scope,
  canEdit,
  onEdit,
  onDelete,
}: {
  scope: Scope;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <li className="flex items-center gap-3 p-4">
      <div className="flex-1">
        <p className="font-medium">{scope.name}</p>
        {scope.notes && <p className="mt-0.5 text-xs text-slate-500">{scope.notes}</p>}
        {scope.task && <p className="mt-0.5 text-xs text-slate-400">→ Task: {scope.task.name}</p>}
      </div>
      <div className="w-24 text-right text-sm">
        <p className="text-slate-500">Giờ</p>
        <p className="font-medium">{formatHours(Number(scope.estimatedHours ?? 0))}</p>
      </div>
      {canEdit && (
        <div className="flex gap-1">
          <button className="rounded p-1 hover:bg-slate-100" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button className="rounded p-1 text-red-600 hover:bg-red-50" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </li>
  );
}

function SortableScopeRow({
  scope,
  canEdit,
  onEdit,
  onDelete,
}: {
  scope: Scope;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: scope.id });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex items-center gap-3 p-4 ${isDragging ? "opacity-40" : ""}`}
    >
      {canEdit && (
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab text-slate-300 hover:text-slate-500"
          title="Kéo để sắp xếp"
        >
          <GripVertical className="h-4 w-4" />
        </button>
      )}
      <div className="flex-1">
        <p className="font-medium">{scope.name}</p>
        {scope.notes && <p className="mt-0.5 text-xs text-slate-500">{scope.notes}</p>}
        {scope.task && <p className="mt-0.5 text-xs text-slate-400">→ Task: {scope.task.name}</p>}
      </div>
      <div className="w-24 text-right text-sm">
        <p className="text-slate-500">Giờ</p>
        <p className="font-medium">{formatHours(Number(scope.estimatedHours ?? 0))}</p>
      </div>
      {canEdit && (
        <div className="flex gap-1">
          <button className="rounded p-1 hover:bg-slate-100" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button className="rounded p-1 text-red-600 hover:bg-red-50" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </li>
  );
}

function ScopeFormModal({
  open,
  onClose,
  projectId,
  scope,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  scope?: Scope | null;
}) {
  const qc = useQueryClient();

  const form = useForm<ScopeCreateInput>({
    resolver: zodResolver(scopeCreateSchema),
    values: scope
      ? {
          name: scope.name,
          notes: scope.notes ?? undefined,
          estimatedHours: scope.estimatedHours ? Number(scope.estimatedHours) : undefined,
        }
      : undefined,
  });

  const save = useMutation({
    mutationFn: async (v: ScopeCreateInput) =>
      scope ? updateScope(scope.id, v) : createScope(projectId, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scopes", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={scope ? "Sửa mục scope" : "Thêm mục scope"} size="lg">
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
        <div>
          <label className="label">Tên mục *</label>
          <input className="input" {...form.register("name")} />
        </div>
        <div>
          <label className="label">Ghi chú</label>
          <textarea rows={2} className="input" {...form.register("notes")} />
        </div>
        <div>
          <label className="label">Giờ ước tính</label>
          <input
            type="number"
            step="0.5"
            className="input"
            {...form.register("estimatedHours", { valueAsNumber: true })}
          />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost border border-slate-200" onClick={onClose}>Hủy</button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>Lưu</button>
        </div>
      </form>
    </Modal>
  );
}
