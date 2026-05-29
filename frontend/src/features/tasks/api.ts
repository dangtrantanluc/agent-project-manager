import { apiClient } from "@/lib/apiClient";
import type { TaskCreateInput, TaskStatus } from "@bb-pm/shared";

export type TaskListItem = {
  id: number;
  name: string;
  status: TaskStatus;
  priority: string;
  deadline: string | null;
  description: string | null;
  totalHours: number;
  assignee: { id: number; fullName: string; avatarUrl: string | null } | null;
  milestone: { id: number; name: string } | null;
  project: { id: number; name: string; code: string | null };
  _count: { worklogs: number; backlogs?: number };
};

export type TaskListParams = {
  projectId?: number;
  status?: TaskStatus;
  assigneeId?: number;
  milestoneId?: number;
  q?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
};

export async function listTasks(params: TaskListParams = {}) {
  const { data } = await apiClient.get<
    TaskListItem[] | {
      data: TaskListItem[];
      meta: { total: number; page: number; pageSize: number };
    }
  >("/tasks", { params });
  if (Array.isArray(data)) {
    const page = params.page ?? 1;
    const pageSize = params.pageSize ?? data.length;
    return { data: data.map(normalizeTask), meta: { total: data.length, page, pageSize } };
  }
  return { ...data, data: data.data.map(normalizeTask) };
}

export async function getTask(id: number) {
  const { data } = await apiClient.get<any>(`/tasks/${id}`);
  return normalizeTask(unwrap(data));
}

export async function createTask(projectId: number, input: TaskCreateInput) {
  const { data } = await apiClient.post<any>(`/tasks/by-project/${projectId}`, input);
  return normalizeTask(unwrap(data));
}

export async function updateTask(id: number, input: Partial<TaskCreateInput>) {
  const { data } = await apiClient.patch<any>(`/tasks/${id}`, input);
  return normalizeTask(unwrap(data));
}

export async function deleteTask(id: number) {
  await apiClient.delete(`/tasks/${id}`);
}

export async function transitionTask(id: number, status: TaskStatus) {
  const { data } = await apiClient.post<any>(`/tasks/${id}/transition`, { status });
  return normalizeTask(unwrap(data));
}

function unwrap<T>(data: T | { data: T }): T {
  return data && typeof data === "object" && "data" in data ? data.data : data;
}

function normalizeTask(task: any): TaskListItem {
  const projectId = task.project?.id ?? task.projectId ?? 0;
  return {
    ...task,
    project: task.project ?? { id: projectId, name: projectId ? `Project #${projectId}` : "—", code: null },
    assignee: task.assignee ?? null,
    milestone: task.milestone ?? null,
    _count: task._count ?? { worklogs: task.worklogCount ?? task.backlogCount ?? 0 },
  };
}
