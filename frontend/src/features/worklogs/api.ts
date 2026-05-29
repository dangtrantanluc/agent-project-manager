import { apiClient } from "@/lib/apiClient";

export type Worklog = {
  id: number;
  workDate: string;
  hours: number;
  description: string | null;
  taskId: number | null;
  projectId: number;
  userId: number;
  task: { id: number; name: string } | null;
  project: { id: number; name: string };
  user: { id: number; fullName: string };
  createdAt: string;
  updatedAt: string;
};

export type WorklogListParams = {
  projectId?: number;
  taskId?: number;
  userId?: number;
  workDateFrom?: string;
  workDateTo?: string;
  mine?: boolean;
  skip?: number;
  limit?: number;
};

export type WorklogCreateInput = {
  workDate: string;
  hours: number;
  description?: string;
  taskId?: number;
  projectId: number;
};

export type WorklogUpdateInput = {
  workDate?: string;
  hours?: number;
  description?: string;
};

export async function listWorklogs(params: WorklogListParams = {}) {
  const { data } = await apiClient.get<
    Worklog[] | {
      data: Worklog[];
      meta: { skip: number; limit: number; total: number };
    }
  >("/worklogs", { params });
  if (Array.isArray(data)) {
    return { data: data.map(normalizeWorklog), meta: { skip: params.skip ?? 0, limit: params.limit ?? data.length, total: data.length } };
  }
  return { ...data, data: data.data.map(normalizeWorklog) };
}

export async function createWorklog(input: WorklogCreateInput) {
  const { data } = await apiClient.post<Worklog | { data: Worklog }>("/worklogs", input);
  return normalizeWorklog(unwrap(data));
}

export async function updateWorklog(id: number, input: WorklogUpdateInput) {
  const { data } = await apiClient.patch<Worklog | { data: Worklog }>(`/worklogs/${id}`, input);
  return normalizeWorklog(unwrap(data));
}

export async function deleteWorklog(id: number) {
  await apiClient.delete(`/worklogs/${id}`);
}

function unwrap<T>(data: T | { data: T }): T {
  return data && typeof data === "object" && "data" in data ? data.data : data;
}

export function normalizeWorklog(raw: any): Worklog {
  const projectId = raw.project?.id ?? raw.projectId ?? 0;
  const userId = raw.user?.id ?? raw.userId ?? 0;
  return {
    ...raw,
    hours: Number(raw.hours),
    project: raw.project ?? { id: projectId, name: projectId ? `Project #${projectId}` : "—" },
    task: raw.task ?? null,
    user: raw.user ?? { id: userId, fullName: userId ? `User #${userId}` : "—" },
  };
}
