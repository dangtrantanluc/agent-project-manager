import { apiClient } from "@/lib/apiClient";

export type DashboardKpis = {
  projects: { active: number; planned: number; completed: number; onHold: number };
  pendingBacklogs: number;
  tasksByStatus: Record<string, number>;
  thisMonth: { hours: number };
};

export type DashboardCharts = {
  hoursByDay: { day: string; hours: number }[];
  hoursByProject: { id: number; name: string; totalHours: number }[];
};

export type DashboardOverview = {
  customer: { name: string; primaryContact: string | null; projectCount: number; active: boolean };
  projectOverview: { total: number; inProgress: number; done: number; paused: number };
  progressSummary: { completionPct: number; doneTasks: number; totalTasks: number; inProgressTasks: number; plannedTasks: number };
  upcomingTimeline: { id: number; type: "milestone" | "task"; title: string; date: string }[];
  agentCapabilities: string[];
};

export async function fetchKpis() {
  const { data } = await apiClient.get<{ data: DashboardKpis }>("/dashboard/kpis");
  return data.data;
}

export async function fetchCharts(range: "7d" | "30d" | "90d" = "30d") {
  const { data } = await apiClient.get<{ data: DashboardCharts }>("/dashboard/charts", { params: { range } });
  return data.data;
}

export type OverviewFilters = {
  projectId?: number;
  projectStatus?: string;
  assigneeId?: number;
  days?: number;
};

export async function fetchOverview(filters: OverviewFilters = {}) {
  const params: Record<string, string | number> = {};
  if (filters.projectId) params.projectId = filters.projectId;
  if (filters.projectStatus) params.projectStatus = filters.projectStatus;
  if (filters.assigneeId) params.assigneeId = filters.assigneeId;
  if (filters.days) params.days = filters.days;
  const { data } = await apiClient.get<{ data: DashboardOverview }>("/dashboard/overview", { params });
  return data.data;
}
