import { Moon, Sun, Monitor } from "lucide-react";
import { useState } from "react";
import { useTheme, type Theme } from "@/features/theme/store";

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Sáng", icon: Sun },
  { value: "dark", label: "Tối", icon: Moon },
  { value: "system", label: "Theo hệ thống", icon: Monitor },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const current = OPTIONS.find((o) => o.value === theme) ?? OPTIONS[2];
  const Icon = current.icon;

  return (
    <div className="relative">
      <button
        className="rounded-md border border-slate-200 bg-white p-2 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"
        onClick={() => setOpen(!open)}
        title={`Theme: ${current.label}`}
      >
        <Icon className="h-3.5 w-3.5" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-40 rounded-md border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
            {OPTIONS.map((o) => {
              const OptionIcon = o.icon;
              return (
                <button
                  key={o.value}
                  onClick={() => { setTheme(o.value); setOpen(false); }}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-700 ${
                    theme === o.value ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400" : ""
                  }`}
                >
                  <OptionIcon className="h-3.5 w-3.5" /> {o.label}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
