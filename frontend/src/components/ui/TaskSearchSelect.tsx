import { useMemo, useRef, useState } from "react";

export type TaskOption = { id: number; code: string | null; name: string };

/** Bỏ dấu + thường hoá để search tiếng Việt không cần gõ dấu ("bao gia" khớp "Báo giá"). */
function fold(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

/**
 * Ô chọn 1 task kiểu search-as-you-type: gõ để lọc theo mã/tên (không dấu cũng
 * khớp), ↑/↓ + Enter để chọn, Esc để đóng. Dùng cho picker phụ thuộc khi dự án
 * nhiều task — thay cho <select> dài khó tìm.
 */
export function TaskSearchSelect({
  options,
  onSelect,
  disabled,
  placeholder = "+ Thêm task phụ thuộc...",
  maxVisible = 50,
}: {
  options: TaskOption[];
  onSelect: (id: number) => void;
  disabled?: boolean;
  placeholder?: string;
  maxVisible?: number;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const fq = fold(q.trim());
    const matches = fq
      ? options.filter((o) => fold(`${o.code ?? ""} ${o.name}`).includes(fq))
      : options;
    return matches.slice(0, maxVisible);
  }, [options, q, maxVisible]);

  const pick = (id: number) => {
    onSelect(id);
    setQ("");
    setActive(0);
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className="relative">
      <input
        ref={inputRef}
        className="input text-sm"
        value={q}
        disabled={disabled}
        placeholder={placeholder}
        role="combobox"
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQ(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(a + 1, filtered.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const sel = filtered[active];
            if (sel) pick(sel.id);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />

      {open && (
        <>
          {/* nền trong suốt để click ra ngoài đóng dropdown */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <ul
            role="listbox"
            className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900"
          >
            {filtered.map((o, i) => (
              <li
                key={o.id}
                role="option"
                aria-selected={i === active}
                className={`flex cursor-pointer items-center gap-1.5 rounded px-2 py-1.5 text-sm ${
                  i === active ? "bg-slate-100 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/50"
                }`}
                // onMouseDown (không onClick) để bắt trước khi input blur đóng dropdown.
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o.id);
                }}
                onMouseEnter={() => setActive(i)}
              >
                {o.code && <span className="font-mono text-xs text-slate-400">{o.code}</span>}
                <span className="min-w-0 truncate">{o.name}</span>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-2 py-1.5 text-xs text-slate-400">Không có task phù hợp.</li>
            )}
            {options.length > maxVisible && q.trim() === "" && (
              <li className="px-2 py-1 text-xs text-slate-400">
                Hiện {maxVisible}/{options.length} task — gõ để tìm thêm.
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}
