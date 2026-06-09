import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";

export type TaskOption = { id: number; name: string };

/** Bỏ dấu tiếng Việt để gõ "ty gia" vẫn khớp "tỷ giá". */
function normalize(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

/** Tên task thường có dạng "[1.4] Tỷ giá hối đoái". Tách mã & phần còn lại. */
function parse(name: string): { code: string | null; label: string; group: string } {
  const m = name.match(/^\s*\[([^\]]+)\]\s*(.*)$/);
  if (!m) return { code: null, label: name, group: "Khác" };
  const code = m[1];
  const major = code.split(".")[0];
  return { code, label: m[2] || name, group: /^\d+$/.test(major) ? `Nhóm ${major}` : "Khác" };
}

type Parsed = TaskOption & ReturnType<typeof parse> & { search: string };

export function TaskCombobox({
  tasks,
  value,
  onChange,
  loading,
  placeholder = "— Không gắn task —",
}: {
  tasks: TaskOption[];
  value: number | undefined;
  onChange: (id: number | undefined) => void;
  loading?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const parsed = useMemo<Parsed[]>(
    () =>
      tasks.map((t) => {
        const p = parse(t.name);
        return { ...t, ...p, search: normalize(`${p.code ?? ""} ${p.label}`) };
      }),
    [tasks],
  );

  const selected = useMemo(() => parsed.find((t) => t.id === value), [parsed, value]);

  // Lọc theo tên & mã (Ý tưởng 1); khi trống → toàn bộ, đã nhóm & sort (Ý tưởng 2).
  const filtered = useMemo(() => {
    const q = normalize(query.trim());
    const list = q ? parsed.filter((t) => t.search.includes(q)) : parsed;
    const sortCode = (a: Parsed, b: Parsed) =>
      (a.code ?? "").localeCompare(b.code ?? "", undefined, { numeric: true });
    return [...list].sort((a, b) =>
      a.group === b.group ? sortCode(a, b) : a.group.localeCompare(b.group, undefined, { numeric: true }),
    );
  }, [parsed, query]);

  // Flat list của các dòng chọn được (để điều hướng bàn phím): index 0 = "không gắn task".
  const rows = useMemo(() => [null, ...filtered.map((t) => t.id)], [filtered]);

  useEffect(() => setActive(0), [query, open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const choose = (id: number | undefined) => {
    onChange(id);
    setOpen(false);
    setQuery("");
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(rows[active] ?? undefined);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  // Chèn header nhóm khi đổi group (chỉ khi không tìm kiếm, để giữ ngữ cảnh cấu trúc).
  let lastGroup: string | null = null;

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className="input flex items-center justify-between gap-2 text-left"
        onClick={() => {
          setOpen((o) => !o);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        <span className={selected ? "" : "text-slate-400"}>
          {selected ? (
            <>
              <span className="font-medium text-slate-900 dark:text-slate-100">{selected.label}</span>
              {selected.code && <span className="ml-2 text-xs text-slate-400">[{selected.code}]</span>}
            </>
          ) : (
            placeholder
          )}
        </span>
        <span className="flex items-center gap-1">
          {selected && (
            <X
              className="h-4 w-4 text-slate-400 hover:text-slate-600"
              onClick={(e) => {
                e.stopPropagation();
                choose(undefined);
              }}
            />
          )}
          <ChevronDown className="h-4 w-4 text-slate-400" />
        </span>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <Search className="h-4 w-4 text-slate-400" />
            <input
              ref={inputRef}
              className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
              placeholder="Gõ tên hoặc mã task…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
            />
          </div>

          <ul className="max-h-72 overflow-auto py-1">
            <li>
              <button
                type="button"
                className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm ${
                  active === 0 ? "bg-brand-50 dark:bg-slate-800" : ""
                }`}
                onMouseEnter={() => setActive(0)}
                onClick={() => choose(undefined)}
              >
                <span className="text-slate-500">— Không gắn task —</span>
                {value === undefined && <Check className="h-4 w-4 text-brand-500" />}
              </button>
            </li>

            {loading && <li className="px-3 py-2 text-sm text-slate-400">Đang tải…</li>}

            {!loading && filtered.length === 0 && (
              <li className="px-3 py-2 text-sm text-slate-400">Không tìm thấy task khớp.</li>
            )}

            {filtered.map((t, idx) => {
              const rowIdx = idx + 1;
              const header = !query.trim() && t.group !== lastGroup ? t.group : null;
              lastGroup = t.group;
              return (
                <li key={t.id}>
                  {header && (
                    <div className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                      {header}
                    </div>
                  )}
                  <button
                    type="button"
                    className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm ${
                      active === rowIdx ? "bg-brand-50 dark:bg-slate-800" : ""
                    }`}
                    onMouseEnter={() => setActive(rowIdx)}
                    onClick={() => choose(t.id)}
                  >
                    <span className="font-medium text-slate-900 dark:text-slate-100">{t.label}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      {t.code && <span className="text-xs text-slate-400">[{t.code}]</span>}
                      {value === t.id && <Check className="h-4 w-4 text-brand-500" />}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
