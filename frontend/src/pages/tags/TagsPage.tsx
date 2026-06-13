import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Pencil, Trash2, Check, X } from "lucide-react";
import { listTags, createTag, updateTag, deleteTag } from "@/features/tags/api";

const PRESET = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6", "#8b5cf6", "#ec4899", "#64748b"];

function ColorDots({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="flex items-center gap-1">
      {PRESET.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={`h-6 w-6 rounded-full ${value.toLowerCase() === c ? "ring-2 ring-offset-1 ring-slate-400" : ""}`}
          style={{ backgroundColor: c }}
          aria-label={c}
        />
      ))}
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-7 w-9 cursor-pointer rounded border border-slate-200 dark:border-slate-700"
        title="Màu tuỳ chọn"
      />
    </div>
  );
}

export function TagsPage() {
  const qc = useQueryClient();
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: () => listTags() });
  const tags = tagsQ.data ?? [];

  const [name, setName] = useState("");
  const [color, setColor] = useState("#3b82f6");
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("#3b82f6");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["tags"] });

  const create = useMutation({
    mutationFn: () => createTag({ name: name.trim(), color }),
    onSuccess: () => { invalidate(); setName(""); },
  });
  const update = useMutation({
    mutationFn: () => updateTag(editId!, { name: editName.trim(), color: editColor }),
    onSuccess: () => { invalidate(); setEditId(null); },
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteTag(id),
    onSuccess: invalidate,
  });

  const startEdit = (id: number, n: string, c: string) => {
    setEditId(id); setEditName(n); setEditColor(c);
  };

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold">Nhãn</h1>
        <p className="text-sm text-slate-500">Tạo và quản lý nhãn để gắn cho task và dự án.</p>
      </div>

      {/* Tạo nhãn mới */}
      <div className="card space-y-3 p-4">
        <h2 className="text-sm font-semibold">Tạo nhãn mới</h2>
        <div className="flex flex-wrap items-center gap-3">
          <input
            className="input w-64"
            placeholder="Tên nhãn…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create.mutate(); }}
          />
          <ColorDots value={color} onChange={setColor} />
          <span
            className="rounded-full px-2 py-0.5 text-xs"
            style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}55` }}
          >
            {name.trim() || "Xem trước"}
          </span>
          <button
            className="btn-primary"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Thêm nhãn
          </button>
        </div>
        {create.isError && (
          <p className="text-sm text-red-600">Không tạo được nhãn (có thể trùng tên).</p>
        )}
      </div>

      {/* Danh sách nhãn */}
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left dark:bg-slate-800/50">
            <tr>
              <th className="p-3">Nhãn</th>
              <th className="p-3">Số task</th>
              <th className="p-3">Số dự án</th>
              <th className="p-3 text-right">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {tags.map((tag) => (
              <tr key={tag.id} className="border-b border-slate-100 dark:border-slate-800">
                {editId === tag.id ? (
                  <>
                    <td className="p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <input className="input w-48" value={editName} onChange={(e) => setEditName(e.target.value)} />
                        <ColorDots value={editColor} onChange={setEditColor} />
                      </div>
                    </td>
                    <td className="p-3 text-slate-500">{tag.taskCount ?? 0}</td>
                    <td className="p-3 text-slate-500">{tag.projectCount ?? 0}</td>
                    <td className="p-3">
                      <div className="flex justify-end gap-2">
                        <button className="btn-primary flex items-center gap-1 text-sm" disabled={!editName.trim() || update.isPending} onClick={() => update.mutate()}>
                          <Check className="h-4 w-4" /> Lưu
                        </button>
                        <button className="btn-secondary flex items-center gap-1 text-sm" onClick={() => setEditId(null)}>
                          <X className="h-4 w-4" /> Hủy
                        </button>
                      </div>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="p-3">
                      <span
                        className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
                        style={{ backgroundColor: `${tag.color}22`, color: tag.color, border: `1px solid ${tag.color}55` }}
                      >
                        {tag.name}
                      </span>
                    </td>
                    <td className="p-3 text-slate-500">{tag.taskCount ?? 0}</td>
                    <td className="p-3 text-slate-500">{tag.projectCount ?? 0}</td>
                    <td className="p-3">
                      <div className="flex justify-end gap-2">
                        <button className="btn-ghost border border-slate-200 dark:border-slate-700" onClick={() => startEdit(tag.id, tag.name, tag.color)} title="Sửa">
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          className="btn-ghost border border-slate-200 text-red-600 dark:border-slate-700"
                          onClick={() => {
                            if (window.confirm(`Xoá nhãn "${tag.name}"? Nhãn sẽ bị gỡ khỏi mọi task/dự án.`)) remove.mutate(tag.id);
                          }}
                          title="Xoá"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </>
                )}
              </tr>
            ))}
            {tags.length === 0 && (
              <tr><td colSpan={4} className="p-6 text-center text-sm text-slate-500">Chưa có nhãn nào. Tạo nhãn đầu tiên ở trên.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
