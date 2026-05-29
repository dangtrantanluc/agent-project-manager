import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "@/features/dashboard/api";
import { useAuth } from "@/features/auth/store";
import { formatDate } from "@/lib/format";
import { Link } from "react-router-dom";
import {
  Bot,
  Building2,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  ListChecks,
} from "lucide-react";

export function DashboardPage() {
  const user = useAuth((s) => s.user);
  const overviewQ = useQuery({ queryKey: ["dashboard-overview"], queryFn: fetchOverview });
  const overview = overviewQ.data;
  const projectOverview = overview?.projectOverview;
  const progressSummary = overview?.progressSummary;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-slate-500">Xin chào {user?.fullName}</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_1.2fr_1.1fr_1.1fr]">
        <div className="card">
          <h2 className="mb-4 text-sm font-semibold text-brand-700">Khách hàng</h2>
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100 text-blue-700">
              <Building2 className="h-6 w-6" />
            </div>
            <div>
              <p className="font-semibold">{overview?.customer.name ?? user?.companyName ?? "-"}</p>
              <p className="mt-1 text-xs text-slate-500">{overview?.customer.projectCount ?? 0} dự án</p>
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">
            <p>Liên hệ chính</p>
            <p className="mt-1 font-medium text-slate-700 dark:text-slate-300">
              {overview?.customer.primaryContact ?? user?.fullName ?? "-"}
            </p>
          </div>
        </div>

        <div className="card">
          <h2 className="mb-4 text-sm font-semibold text-brand-700">Tổng quan dự án</h2>
          <div className="grid grid-cols-2 gap-4 text-center">
            <MiniStat label="Tổng dự án" value={projectOverview?.total ?? 0} />
            <MiniStat label="Đang thực hiện" value={projectOverview?.inProgress ?? 0} />
            <MiniStat label="Đã hoàn thành" value={projectOverview?.done ?? 0} />
            <MiniStat label="Tạm dừng" value={projectOverview?.paused ?? 0} />
          </div>
        </div>

        <div className="card">
          <h2 className="mb-3 text-sm font-semibold text-brand-700">Tiến độ tổng hợp</h2>
          <div className="flex items-center gap-4">
            <div
              className="grid h-28 w-28 shrink-0 place-items-center rounded-full"
              style={{ background: buildProgressGradient(progressSummary) }}
            >
              <div className="grid h-20 w-20 place-items-center rounded-full bg-white text-center dark:bg-slate-900">
                <span className="text-2xl font-bold">{progressSummary?.completionPct ?? 0}%</span>
              </div>
            </div>
            <div className="space-y-2 text-xs">
              <LegendDot color="bg-blue-600" label="Hoàn thành" />
              <LegendDot color="bg-orange-500" label="Đang thực hiện" />
              <LegendDot color="bg-slate-300" label="Chưa bắt đầu" />
            </div>
          </div>
        </div>

        <div className="card">
          <h2 className="mb-3 text-sm font-semibold text-brand-700">Timeline sắp tới</h2>
          <ul className="space-y-2">
            {(overview?.upcomingTimeline ?? []).slice(0, 6).map((item) => (
              <li key={`${item.type}-${item.id}`} className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate">
                  <span className={`mr-2 inline-block h-2 w-2 rounded-full ${item.type === "milestone" ? "bg-slate-600" : "bg-blue-600"}`} />
                  {item.title}
                </span>
                <span className="whitespace-nowrap text-slate-500">{formatDate(item.date)}</span>
              </li>
            ))}
            {!overview?.upcomingTimeline.length && (
              <li className="py-4 text-center text-xs text-slate-500">Chưa có timeline.</li>
            )}
          </ul>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_1.2fr]">
        <DetailCard
          title="Chi tiết dự án"
          icon={<ClipboardList className="h-5 w-5" />}
          actions={<Link to="/projects" className="text-xs font-medium text-brand-700 hover:underline">Xem dự án</Link>}
        >
          <MetricRow label="Tổng dự án" value={projectOverview?.total ?? 0} pct={100} color="bg-slate-500" />
          <MetricRow label="Đang thực hiện" value={projectOverview?.inProgress ?? 0} pct={percent(projectOverview?.inProgress, projectOverview?.total)} color="bg-blue-600" />
          <MetricRow label="Đã hoàn thành" value={projectOverview?.done ?? 0} pct={percent(projectOverview?.done, projectOverview?.total)} color="bg-emerald-500" />
          <MetricRow label="Tạm dừng / hủy" value={projectOverview?.paused ?? 0} pct={percent(projectOverview?.paused, projectOverview?.total)} color="bg-amber-500" />
        </DetailCard>

        <DetailCard
          title="Chi tiết tiến độ"
          icon={<ListChecks className="h-5 w-5" />}
          actions={<Link to="/tasks" className="text-xs font-medium text-brand-700 hover:underline">Xem task</Link>}
        >
          <MetricRow label="Tổng task" value={progressSummary?.totalTasks ?? 0} pct={100} color="bg-slate-500" />
          <MetricRow label="Hoàn thành" value={progressSummary?.doneTasks ?? 0} pct={percent(progressSummary?.doneTasks, progressSummary?.totalTasks)} color="bg-blue-600" />
          <MetricRow label="Đang thực hiện" value={progressSummary?.inProgressTasks ?? 0} pct={percent(progressSummary?.inProgressTasks, progressSummary?.totalTasks)} color="bg-orange-500" />
          <MetricRow label="Chưa bắt đầu" value={progressSummary?.plannedTasks ?? 0} pct={percent(progressSummary?.plannedTasks, progressSummary?.totalTasks)} color="bg-slate-300" />
        </DetailCard>

        <DetailCard title="Timeline chi tiết" icon={<CalendarDays className="h-5 w-5" />}>
          <div className="space-y-2">
            {(overview?.upcomingTimeline ?? []).map((item) => (
              <Link
                key={`${item.type}-${item.id}`}
                to={item.type === "task" ? "/tasks" : "/projects"}
                className="flex items-center justify-between gap-3 rounded-md border border-slate-100 px-3 py-2 text-sm transition hover:border-brand-200 hover:bg-brand-50/50 dark:border-slate-800 dark:hover:bg-brand-500/10"
              >
                <span className="min-w-0">
                  <span className="mb-1 flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${item.type === "task" ? "bg-blue-600" : "bg-slate-600"}`} />
                    <span className="truncate font-medium">{item.title}</span>
                  </span>
                  <span className="text-xs text-slate-500">{item.type === "task" ? "Task" : "Milestone"}</span>
                </span>
                <span className="shrink-0 text-right text-xs text-slate-500">
                  <span className="block font-medium text-slate-700 dark:text-slate-300">{formatDate(item.date)}</span>
                  <span>{daysUntil(item.date)}</span>
                </span>
              </Link>
            ))}
            {!overview?.upcomingTimeline.length && (
              <p className="py-8 text-center text-sm text-slate-500">Chưa có timeline.</p>
            )}
          </div>
        </DetailCard>
      </div>

      <div className="card overflow-hidden bg-gradient-to-br from-white to-blue-50 dark:from-slate-900 dark:to-slate-900">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-4">
            <div className="grid h-20 w-20 place-items-center rounded-full bg-blue-600 text-white shadow-lg shadow-blue-600/20">
              <Bot className="h-10 w-10" />
            </div>
            <div>
              <h2 className="text-xl font-bold">PM Agent</h2>
              <p className="text-sm text-slate-500">Theo dõi tình trạng dự án và nhắc việc từ dữ liệu hiện tại.</p>
            </div>
          </div>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            {(overview?.agentCapabilities ?? ["Nhắc việc", "Theo dõi tiến độ", "Tóm tắt tình trạng", "Việc còn thiếu"]).map((capability) => (
              <div key={capability} className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-blue-600" />
                <span>{capability}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-3xl font-bold">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{label}</p>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
  );
}

function DetailCard({
  title,
  icon,
  actions,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="card">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
            {icon}
          </span>
          <h2 className="font-semibold">{title}</h2>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

function MetricRow({
  label,
  value,
  pct,
  color,
}: {
  label: string;
  value: number;
  pct: number;
  color: string;
}) {
  return (
    <div className="mb-4 last:mb-0">
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-slate-600 dark:text-slate-300">{label}</span>
        <span className="font-semibold">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }} />
      </div>
    </div>
  );
}

function percent(value: number | undefined, total: number | undefined) {
  if (!value || !total) return 0;
  return Math.round((value * 100) / total);
}

function buildProgressGradient(summary: { doneTasks: number; inProgressTasks: number; plannedTasks: number; totalTasks: number } | undefined) {
  const total = summary?.totalTasks ?? 0;
  if (!total) return "conic-gradient(#e2e8f0 0deg 360deg)";
  const done = ((summary?.doneTasks ?? 0) / total) * 360;
  const inProgress = done + ((summary?.inProgressTasks ?? 0) / total) * 360;
  return `conic-gradient(#2563eb 0deg ${done}deg, #f97316 ${done}deg ${inProgress}deg, #e2e8f0 ${inProgress}deg 360deg)`;
}

function daysUntil(value: string) {
  const today = new Date();
  const target = new Date(value);
  today.setHours(0, 0, 0, 0);
  target.setHours(0, 0, 0, 0);
  const days = Math.round((target.getTime() - today.getTime()) / 86_400_000);
  if (days <= 0) return "Hôm nay";
  return `Còn ${days} ngày`;
}
