import { useQuery } from "@tanstack/react-query";
import { fetchOverview, type OverviewFilters } from "@/features/dashboard/api";
import { listProjects } from "@/features/projects/api";
import { listUsers } from "@/features/users/api";
import { useAuth } from "@/features/auth/store";
import { formatDate } from "@/lib/format";
import { Link } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  CalendarDays,
  ClipboardList,
  ListChecks,
  SlidersHorizontal,
  X,
} from "lucide-react";

const PROJECT_STATUSES = [
  { value: "IN_PROGRESS", label: "Đang thực hiện" },
  { value: "PLANNED", label: "Lên kế hoạch" },
  { value: "DONE", label: "Đã hoàn thành" },
  { value: "PENDING", label: "Tạm dừng" },
  { value: "CANCELLED", label: "Đã hủy" },
];

const TIME_RANGES = [
  { value: 0, label: "Tất cả thời gian" },
  { value: 7, label: "7 ngày tới" },
  { value: 30, label: "30 ngày tới" },
  { value: 90, label: "90 ngày tới" },
];

export function DashboardPage() {
  const user = useAuth((s) => s.user);

  const [projectId, setProjectId] = useState<number | undefined>();
  const [projectStatus, setProjectStatus] = useState<string | undefined>();
  const [assigneeId, setAssigneeId] = useState<number | undefined>();
  const [days, setDays] = useState<number>(0);

  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  const filters: OverviewFilters = useMemo(
    () => ({ projectId, projectStatus, assigneeId, days: days || undefined }),
    [projectId, projectStatus, assigneeId, days],
  );
  const activeCount =
    (projectId ? 1 : 0) + (projectStatus ? 1 : 0) + (assigneeId ? 1 : 0) + (days ? 1 : 0);
  const hasFilters = activeCount > 0;

  const clearFilters = () => {
    setProjectId(undefined);
    setProjectStatus(undefined);
    setAssigneeId(undefined);
    setDays(0);
  };

  useEffect(() => {
    if (!filterOpen) return;
    const onDown = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) setFilterOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [filterOpen]);

  const projectsQ = useQuery({ queryKey: ["projects-lite"], queryFn: () => listProjects({ pageSize: 500 }) });
  const usersQ = useQuery({ queryKey: ["users-lite"], queryFn: listUsers });

  const overviewQ = useQuery({
    queryKey: ["dashboard-overview", filters],
    queryFn: () => fetchOverview(filters),
  });
  const overview = overviewQ.data;
  const projectOverview = overview?.projectOverview;
  const progressSummary = overview?.progressSummary;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-slate-500">Xin chào {user?.fullName}</p>
        </div>

        <div className="relative" ref={filterRef}>
          <button
            type="button"
            className="btn-ghost relative flex items-center gap-1.5 border border-slate-200 dark:border-slate-700"
            onClick={() => setFilterOpen((o) => !o)}
          >
            <SlidersHorizontal className="h-4 w-4" />
            <span className="hidden sm:inline">Bộ lọc</span>
            {activeCount > 0 && (
              <span className="grid h-5 min-w-[1.25rem] place-items-center rounded-full bg-brand-600 px-1 text-xs font-semibold text-white">
                {activeCount}
              </span>
            )}
          </button>

          {filterOpen && (
            <div className="absolute right-0 z-50 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-4 shadow-xl dark:border-slate-700 dark:bg-slate-900">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold">Bộ lọc</h3>
                {hasFilters && (
                  <button
                    type="button"
                    className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                    onClick={clearFilters}
                  >
                    <X className="h-3.5 w-3.5" /> Xóa lọc
                  </button>
                )}
              </div>

              <div className="space-y-3">
                <FilterField label="Dự án">
                  <select
                    className="input"
                    value={projectId ?? ""}
                    onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : undefined)}
                  >
                    <option value="">Tất cả dự án</option>
                    {projectsQ.data?.data.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </FilterField>

                <FilterField label="Trạng thái dự án">
                  <select
                    className="input"
                    value={projectStatus ?? ""}
                    onChange={(e) => setProjectStatus(e.target.value || undefined)}
                  >
                    <option value="">Tất cả trạng thái</option>
                    {PROJECT_STATUSES.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </FilterField>

                <FilterField label="Người phụ trách">
                  <select
                    className="input"
                    value={assigneeId ?? ""}
                    onChange={(e) => setAssigneeId(e.target.value ? Number(e.target.value) : undefined)}
                  >
                    <option value="">Tất cả thành viên</option>
                    {usersQ.data?.map((u) => (
                      <option key={u.id} value={u.id}>{u.fullName}</option>
                    ))}
                  </select>
                </FilterField>

                <FilterField label="Khoảng thời gian">
                  <select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                    {TIME_RANGES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </FilterField>
              </div>
            </div>
          )}
        </div>
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

    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-[10rem] flex-1">
      <label className="label">{label}</label>
      {children}
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
