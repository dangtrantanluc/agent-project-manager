import { NavLink, Outlet, Navigate } from "react-router-dom";
import { Users, Building2, Coins, Activity } from "lucide-react";
import { useAuth } from "@/features/auth/store";

const tabs = [
  { to: "/settings/users", label: "Thành viên", icon: Users },
  { to: "/settings/company", label: "Công ty", icon: Building2 },
  { to: "/settings/currencies", label: "Tiền tệ", icon: Coins },
  { to: "/settings/agent-audit", label: "Agent audit", icon: Activity },
];

export function SettingsLayout() {
  const user = useAuth((s) => s.user);
  // Agent audit is opened up to MANAGER too — they're the primary
  // consumers of the audit dashboard for debugging follow-ups.
  const canSeeSettings =
    user?.role === "ADMIN" || user?.isSuperAdmin || user?.role === "MANAGER";
  if (!canSeeSettings) return <Navigate to="/dashboard" replace />;

  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-bold">Settings</h1>
      <div className="mb-6 border-b border-slate-200">
        <nav className="flex gap-1">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                `flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm ${
                  isActive
                    ? "border-brand-600 font-medium text-brand-700"
                    : "border-transparent text-slate-500 hover:text-slate-700"
                }`
              }
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <Outlet />
    </div>
  );
}
