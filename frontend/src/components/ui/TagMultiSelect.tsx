import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { listTags, createTag } from "@/features/tags/api";

/** Chọn nhiều nhãn (controlled). Cho phép tạo nhãn mới ngay trong dropdown. */
export function TagMultiSelect({
  value,
  onChange,
  placeholder = "Chọn nhãn…",
}: {
  value: number[];
  onChange: (ids: number[]) => void;
  placeholder?: string;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: () => listTags() });
  const tags = tagsQ.data ?? [];

  const create = useMutation({
    mutationFn: () => createTag({ name: newName.trim() }),
    onSuccess: (tag) => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      onChange([...value, tag.id]);
      setNewName("");
    },
  });

  const toggle = (id: number) =>
    onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);

  const selected = tags.filter((t) => value.includes(t.id));

  return (
    <div className="relative">
      <button
        type="button"
        className="input flex min-h-[38px] flex-wrap items-center gap-1 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        {selected.length ? (
          selected.map((t) => (
            <span
              key={t.id}
              className="rounded-full px-2 py-0.5 text-xs"
              style={{ backgroundColor: `${t.color}22`, color: t.color }}
            >
              {t.name}
            </span>
          ))
        ) : (
          <span className="text-slate-400">{placeholder}</span>
        )}
      </button>

      {open && (
        <>
          {/* nền trong suốt để click ra ngoài đóng dropdown */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white p-2 shadow-lg dark:border-slate-700 dark:bg-slate-900">
            {tags.map((t) => (
              <label
                key={t.id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                <input type="checkbox" checked={value.includes(t.id)} onChange={() => toggle(t.id)} />
                <span style={{ color: t.color }}>●</span>
                <span className="text-sm">{t.name}</span>
              </label>
            ))}
            {tags.length === 0 && (
              <p className="px-2 py-1 text-xs text-slate-400">Chưa có nhãn nào.</p>
            )}
            <div className="mt-2 flex gap-1 border-t border-slate-100 pt-2 dark:border-slate-800">
              <input
                className="input flex-1 text-sm"
                placeholder="Tạo nhãn mới…"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (newName.trim()) create.mutate();
                  }
                }}
              />
              <button
                type="button"
                className="btn-secondary text-sm"
                disabled={!newName.trim() || create.isPending}
                onClick={() => create.mutate()}
              >
                Thêm
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
