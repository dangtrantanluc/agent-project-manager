import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/store";
import {
  LayoutDashboard, FolderKanban, ListTodo, ClipboardCheck, LogOut,
  Settings,
} from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { LanguageSwitcher } from "./ui/LanguageSwitcher";
import { ThemeToggle } from "./ui/ThemeToggle";
import { NotificationBell } from "./NotificationBell";
import { BlueboltLogo } from "./ui/BlueboltLogo";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  const nav2 = useNavigate();
  const { user, clear } = useAuth();
  const { t } = useTranslation();
  const isAdmin = user?.role === "ADMIN" || user?.isSuperAdmin;

  const logout = async () => {
    try { await apiClient.post("/auth/logout"); } catch { /* ignore */ }
    clear();
    toast.success("Đã đăng xuất");
    nav2("/login", { replace: true });
  };

  const nav = [
    { to: "/dashboard", label: t("nav.dashboard"), icon: LayoutDashboard },
    { to: "/projects",  label: t("nav.projects"),  icon: FolderKanban },
    { to: "/tasks",     label: t("nav.tasks"),     icon: ListTodo },
    { to: "/worklogs",  label: t("nav.worklogs"),  icon: ClipboardCheck },
  ];

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-72 flex-shrink-0 flex-col overflow-y-auto border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center px-4 py-6">
          <Link to="/dashboard">
            <BlueboltLogo size="md" />
          </Link>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {nav.map((item) => {
            const active = pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2.5 text-[15px] ${
                  active
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400"
                    : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                <Icon className="h-5 w-5" /> {item.label}
              </Link>
            );
          })}
          {isAdmin && (
            <Link
              to="/settings"
              className={`mt-4 flex items-center gap-2.5 rounded-md px-3 py-2.5 text-[15px] ${
                pathname.startsWith("/settings")
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400"
                  : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              }`}
            >
              <Settings className="h-5 w-5" /> Settings
            </Link>
          )}
        </nav>

        <div className="border-t border-slate-200 p-3 dark:border-slate-800">
          <Link
            to="/profile"
            className={`flex items-center gap-2.5 rounded-md p-2 text-[15px] ${
              pathname.startsWith("/profile")
                ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400"
                : "hover:bg-slate-100 dark:hover:bg-slate-800"
            }`}
          >
            <div className="h-10 w-10 overflow-hidden rounded-full bg-slate-100 ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700">
              {user?.avatarUrl ? (
                <img src={user.avatarUrl} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-sm font-bold text-slate-400">
                  {user?.fullName?.slice(0, 1).toUpperCase() ?? "?"}
                </div>
              )}
            </div>
            <div className="flex-1 overflow-hidden">
              <p className="truncate text-sm font-medium">{user?.fullName}</p>
              <p className="truncate text-xs text-slate-400 dark:text-slate-500">{user?.role}</p>
            </div>
          </Link>
          <button onClick={logout} className="btn-ghost mt-2 w-full justify-start gap-2">
            <LogOut className="h-4 w-4" /> {t("auth.logout")}
          </button>
        </div>
      </aside>

      <div className="flex min-h-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-2 border-b border-slate-200 bg-white px-6 py-2 dark:border-slate-800 dark:bg-slate-900">
          <NotificationBell />
          <ThemeToggle />
          <LanguageSwitcher />
        </header>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
