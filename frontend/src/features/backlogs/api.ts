import { apiClient } from "@/lib/apiClient";
import type { BacklogCreateInput, BacklogStatus } from "@bb-pm/shared";

export type Backlog = {
  id: number;
  status: BacklogStatus;
  workDate: string;
  hours: string;
  description: string | null;
  rejectedReason: string | null;
  approvedAt: string | null;
  task: { id: number; name: string } | null;
  project: { id: number; name: string; code: string | null };
  user: { id: number; fullName: string; avatarUrl: string | null };
  approver: { id: number; fullName: string } | null;
  currency: { id: number; code: string; symbol: string } | null;
};

export type BacklogListParams = {
  status?: BacklogStatus;
  userId?: number;
  mine?: boolean;
  projectId?: number;
  taskId?: number;
  workDateFrom?: string;
  workDateTo?: string;
  page?: number;
  pageSize?: number;
};

export async function listBacklogs(params: BacklogListParams = {}) {
  const { data } = await apiClient.get<
    Backlog[] | {
      data: Backlog[];
      meta: { page: number; pageSize: number; total: number };
    }
  >("/backlogs", { params });
  if (Array.isArray(data)) {
    const page = params.page ?? 1;
    const pageSize = params.pageSize ?? data.length;
    return { data: data.map(normalizeBacklog), meta: { page, pageSize, total: data.length } };
  }
  return { ...data, data: data.data.map(normalizeBacklog) };
}

export async function createBacklog(taskId: number, input: BacklogCreateInput) {
  const { data } = await apiClient.post<Backlog | { data: Backlog }>(`/backlogs/by-task/${taskId}`, input);
  return normalizeBacklog(unwrap(data));
}

export async function createProjectBacklog(projectId: number, input: BacklogCreateInput & { taskId?: number }) {
  const { data } = await apiClient.post<Backlog | { data: Backlog }>(`/backlogs/by-project/${projectId}`, input);
  return normalizeBacklog(unwrap(data));
}

export async function updateBacklog(id: number, input: Partial<BacklogCreateInput>) {
  const { data } = await apiClient.patch<Backlog | { data: Backlog }>(`/backlogs/${id}`, input);
  return normalizeBacklog(unwrap(data));
}

export async function deleteBacklog(id: number) {
  await apiClient.delete(`/backlogs/${id}`);
}

export async function approveBacklog(id: number) {
  const { data } = await apiClient.post<Backlog | { data: Backlog }>(`/backlogs/${id}/approve`);
  return normalizeBacklog(unwrap(data));
}

export async function rejectBacklog(id: number, reason: string) {
  const { data } = await apiClient.post<Backlog | { data: Backlog }>(`/backlogs/${id}/reject`, { reason });
  return normalizeBacklog(unwrap(data));
}

export async function resetBacklog(id: number) {
  const { data } = await apiClient.post<Backlog | { data: Backlog }>(`/backlogs/${id}/reset`);
  return normalizeBacklog(unwrap(data));
}

function unwrap<T>(data: T | { data: T }): T {
  return data && typeof data === "object" && "data" in data ? data.data : data;
}

function normalizeBacklog(backlog: any): Backlog {
  const projectId = backlog.project?.id ?? backlog.projectId ?? 0;
  const userId = backlog.user?.id ?? backlog.userId ?? 0;
  return {
    ...backlog,
    project: backlog.project ?? { id: projectId, name: projectId ? `Project #${projectId}` : "—", code: null },
    task: backlog.task ?? null,
    user: backlog.user ?? { id: userId, fullName: userId ? `User #${userId}` : "—", avatarUrl: null },
    approver: backlog.approver ?? null,
    currency: backlog.currency ?? null,
  };
}
