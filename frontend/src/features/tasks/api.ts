import { apiClient } from "@/lib/apiClient";
import type { TaskCreateInput, TaskStatus } from "@bb-pm/shared";

export type TaskListItem = {
  id: number;
  name: string;
  status: TaskStatus;
  priority: string;
  deadline: string | null;
  endAt: string | null;
  description: string | null;
  totalHours: number;
  assignee: { id: number; fullName: string; avatarUrl: string | null } | null;
  milestone: { id: number; name: string } | null;
  project: { id: number; name: string; code: string | null };
  tags: { id: number; name: string; color: string }[];
  _count: { worklogs: number; backlogs?: number };
  /** Số blocker chưa gỡ (BE: open_blockers). >0 => task đang kẹt. */
  blockerCount: number;
};

export type TaskListParams = {
  projectId?: number;
  status?: TaskStatus;
  assigneeId?: number;
  milestoneId?: number;
  tagId?: number;
  tagIds?: number[];
  priority?: string;
  deadlineFrom?: string;
  deadlineTo?: string;
  q?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
};

/** Task gợi ý để log worklog: ưu tiên task của user -> deadline gần -> mới cập
 * nhật, loại DONE. Dùng cho quick-add (giảm friction tìm task). */
export type TaskCandidate = {
  id: number;
  name: string;
  status: TaskStatus;
  deadline: string | null;
  assigneeId: number | null;
  mine: boolean;
};

export async function listTaskCandidates(params: {
  projectId: number;
  q?: string;
  limit?: number;
}) {
  const { data } = await apiClient.get<{ data: TaskCandidate[] } | TaskCandidate[]>(
    "/tasks/candidates",
    { params },
  );
  return Array.isArray(data) ? data : data.data;
}

export async function listTasks(params: TaskListParams = {}) {
  const { data } = await apiClient.get<
    TaskListItem[] | {
      data: TaskListItem[];
      meta: { total: number; page: number; pageSize: number };
    }
  >("/tasks", {
    params,
    // Serialize mảng dạng lặp `tagIds=1&tagIds=2` (FastAPI list[int]), KHÔNG `tagIds[]=`.
    paramsSerializer: { indexes: null },
  });
  if (Array.isArray(data)) {
    const page = params.page ?? 1;
    const pageSize = params.pageSize ?? data.length;
    return { data: data.map(normalizeTask), meta: { total: data.length, page, pageSize } };
  }
  return { ...data, data: data.data.map(normalizeTask) };
}

/** Shape thô từ BE trước khi normalize: các scalar luôn có (BE trả đủ); chỉ nested
 * object & _count là optional vì normalize sẽ điền. An toàn hơn `any`. */
type RawTask = Omit<TaskListItem, "project" | "assignee" | "milestone" | "tags" | "_count" | "blockerCount"> & {
  project?: TaskListItem["project"] | null;
  assignee?: TaskListItem["assignee"];
  milestone?: TaskListItem["milestone"];
  tags?: TaskListItem["tags"];
  _count?: TaskListItem["_count"];
  blockerCount?: number;
  projectId?: number;
  worklogCount?: number;
  backlogCount?: number;
};
type Wrapped<T> = T | { data: T };

export async function getTask(id: number) {
  const { data } = await apiClient.get<Wrapped<RawTask>>(`/tasks/${id}`);
  return normalizeTask(unwrap(data));
}

export async function createTask(projectId: number, input: TaskCreateInput) {
  const { data } = await apiClient.post<Wrapped<RawTask>>(`/tasks/by-project/${projectId}`, input);
  return normalizeTask(unwrap(data));
}

export async function updateTask(id: number, input: Partial<TaskCreateInput>) {
  const { data } = await apiClient.patch<Wrapped<RawTask>>(`/tasks/${id}`, input);
  return normalizeTask(unwrap(data));
}

export async function deleteTask(id: number) {
  await apiClient.delete(`/tasks/${id}`);
}

export async function transitionTask(id: number, status: TaskStatus) {
  const { data } = await apiClient.post<Wrapped<RawTask>>(`/tasks/${id}/transition`, { status });
  return normalizeTask(unwrap(data));
}

function unwrap<T>(data: T | { data: T }): T {
  return data && typeof data === "object" && "data" in data ? data.data : data;
}

function normalizeTask(task: RawTask): TaskListItem {
  const projectId = task.project?.id ?? task.projectId ?? 0;
  return {
    ...task,
    project: task.project ?? { id: projectId, name: projectId ? `Project #${projectId}` : "—", code: null },
    assignee: task.assignee ?? null,
    milestone: task.milestone ?? null,
    tags: task.tags ?? [],
    _count: task._count ?? { worklogs: task.worklogCount ?? task.backlogCount ?? 0 },
    blockerCount: task.blockerCount ?? 0,
  };
}

export type Blocker = {
  id: number;
  taskId: number;
  severity: string;
  description: string;
  resolvedAt: string | null;
  createdAt: string;
};

export async function listBlockers(taskId: number) {
  const { data } = await apiClient.get<Blocker[]>(`/tasks/${taskId}/blockers`);
  return data;
}

export async function resolveBlocker(blockerId: number) {
  const { data } = await apiClient.patch<Blocker>(`/tasks/blockers/${blockerId}/resolve`);
  return data;
}
