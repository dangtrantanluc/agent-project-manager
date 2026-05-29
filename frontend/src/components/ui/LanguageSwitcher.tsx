import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import { updateMe } from "@/features/profile/api";
import { useAuth } from "@/features/auth/store";

const LANGS = [
  { code: "vi_VN", label: "Tiếng Việt", flag: "🇻🇳" },
  { code: "en_US", label: "English", flag: "🇺🇸" },
];

export function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const setUser = useAuth((s) => s.setUser);
  const user = useAuth((s) => s.user);
  const current = LANGS.find((l) => l.code === i18n.language) ?? LANGS[0];

  const change = async (code: string) => {
    i18n.changeLanguage(code);
    setOpen(false);
    if (user) {
      try {
        await updateMe({ lang: code as any });
        setUser({ ...user, lang: code });
      } catch { /* ignore */ }
    }
  };

  return (
    <div className="relative">
      <button
        className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"
        onClick={() => setOpen(!open)}
      >
        <Globe className="h-3.5 w-3.5" />
        <span>{current.flag}</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-40 rounded-md border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
            {LANGS.map((l) => (
              <button
                key={l.code}
                onClick={() => change(l.code)}
                className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-700 ${
                  i18n.language === l.code ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400" : ""
                }`}
              >
                <span>{l.flag}</span> {l.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
