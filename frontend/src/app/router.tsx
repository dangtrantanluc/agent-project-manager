import { Navigate, Route, Routes } from "react-router-dom";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { ProjectListPage } from "@/pages/projects/ProjectListPage";
import { ProjectDetailPage } from "@/pages/projects/ProjectDetailPage";
import { TasksPage } from "@/pages/tasks/TasksPage";
import { WorklogsPage } from "@/pages/worklogs/WorklogsPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { SettingsLayout } from "@/pages/settings/SettingsLayout";
import { UsersPage } from "@/pages/settings/UsersPage";
import { CompanyPage } from "@/pages/settings/CompanyPage";
import { CurrenciesPage } from "@/pages/settings/CurrenciesPage";
import { AgentAuditPage } from "@/pages/settings/AgentAuditPage";
import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/features/auth/store";

function Protected({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.accessToken);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function Router() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/*"
        element={
          <Protected>
            <AppShell>
              <Routes>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/projects" element={<ProjectListPage />} />
                <Route path="/projects/:id" element={<ProjectDetailPage />} />
                <Route path="/tasks" element={<TasksPage />} />
                <Route path="/worklogs" element={<WorklogsPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/settings" element={<SettingsLayout />}>
                  <Route index element={<Navigate to="users" replace />} />
                  <Route path="users" element={<UsersPage />} />
                  <Route path="company" element={<CompanyPage />} />
                  <Route path="currencies" element={<CurrenciesPage />} />
                  <Route path="agent-audit" element={<AgentAuditPage />} />
                </Route>
                <Route path="*" element={<div className="p-8">404 — Not Found</div>} />
              </Routes>
            </AppShell>
          </Protected>
        }
      />
    </Routes>
  );
}
