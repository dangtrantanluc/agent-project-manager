import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { statusColors, statusLabels } from "@/lib/format";
import type { TaskStatus } from "@bb-pm/shared";

const STATUSES: TaskStatus[] = ["TODO", "IN_PROGRESS", "DONE", "CANCELLED"];

/** Badge trạng thái bấm được — mở menu chọn nhanh trạng thái mới cho task. */
export function StatusSelect({
  value,
  onChange,
}: {
  value: TaskStatus;
  onChange: (s: TaskStatus) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="inline-flex items-center gap-1 rounded-full focus:outline-none"
        title="Đổi trạng thái"
      >
        <Badge className={statusColors[value]}>
          <span className="inline-flex items-center gap-1">
            {statusLabels[value]}
            <ChevronDown className="h-3 w-3 opacity-60" />
          </span>
        </Badge>
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-40 rounded-md border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                if (s !== value) onChange(s);
              }}
              className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Badge className={statusColors[s]}>{statusLabels[s]}</Badge>
              {s === value && <Check className="h-3.5 w-3.5 text-brand-600" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
