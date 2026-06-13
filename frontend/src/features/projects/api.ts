import { apiClient } from "@/lib/apiClient";
import type { ProjectCreateInput, ProjectUpdateInput, ProjectStatus } from "@bb-pm/shared";
import type { Milestone } from "@/features/milestones/api";

export type ProjectListItem = {
  id: number;
  name: string;
  code: string | null;
  status: ProjectStatus;
  priority: string;
  startDate: string | null;
  endDate: string | null;
  totalHours: number;
  taskCount: number;
  memberCount: number;
  owner: { id: number; fullName: string; avatarUrl: string | null };
  customerName: string | null;
  description?: string | null;
  currency: { id: number; code: string; symbol: string } | null;
  tags: { id: number; name: string; color: string }[];
  gapoThreadId?: string | null;
};

type ProjectResponse = ProjectListItem & {
  description?: string | null;
  worklogCount?: number;
  backlogCount?: number;
  scopeCount?: number;
  milestoneCount?: number;
  ownerId?: number;
  accountManagerId?: number | null;
  currencyId?: number | null;
  createdAt?: string;
  updatedAt?: string;
  _count: {
    tasks: number;
    worklogs: number;
    backlogs: number;
    members: number;
    milestones: number;
  };
  milestones: Milestone[];
};

/** Shape thô từ BE trước normalize: scalar luôn có; nested/_count/owner optional
 * (normalize sẽ điền, dùng _count thay *Count). An toàn hơn `any`. */
type RawProject = Omit<
  ProjectResponse,
  "owner" | "currency" | "tags" | "milestones" | "_count" | "taskCount" | "memberCount"
> & {
  owner?: ProjectResponse["owner"];
  currency?: ProjectResponse["currency"];
  tags?: ProjectResponse["tags"];
  milestones?: ProjectResponse["milestones"];
  taskCount?: number;
  memberCount?: number;
  ownerId?: number;
  _count?: Partial<ProjectResponse["_count"]>;
};

export type ProjectListParams = {
  status?: ProjectStatus;
  q?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
};

export async function listProjects(params: ProjectListParams = {}) {
  const { data } = await apiClient.get<
    | ProjectResponse[]
    | {
    data: ProjectListItem[];
    meta: { page: number; pageSize: number; total: number };
      }
  >("/projects", { params });

  if (Array.isArray(data)) {
    const page = params.page ?? 1;
    const pageSize = params.pageSize ?? data.length;
    return {
      data: data.map(normalizeProject),
      meta: { page, pageSize, total: data.length },
    };
  }

  return {
    ...data,
    data: data.data.map(normalizeProject),
  };
}

export async function getProject(id: number) {
  const { data } = await apiClient.get<ProjectResponse | { data: ProjectResponse }>(`/projects/${id}`);
  return normalizeProject("data" in data ? data.data : data);
}

export async function createProject(input: ProjectCreateInput) {
  const { data } = await apiClient.post<ProjectResponse | { data: ProjectResponse }>("/projects", input);
  return normalizeProject("data" in data ? data.data : data);
}

export async function updateProject(id: number, input: ProjectUpdateInput) {
  const { data } = await apiClient.patch<ProjectResponse | { data: ProjectResponse }>(`/projects/${id}`, input);
  return normalizeProject("data" in data ? data.data : data);
}

export async function deleteProject(id: number) {
  await apiClient.delete(`/projects/${id}`);
}

export async function transitionProject(id: number, status: ProjectStatus) {
  const { data } = await apiClient.post<ProjectResponse | { data: ProjectResponse }>(`/projects/${id}/transition`, { status });
  return normalizeProject("data" in data ? data.data : data);
}

function normalizeProject(project: RawProject): ProjectResponse {
  const taskCount = project.taskCount ?? project._count?.tasks ?? 0;
  const worklogCount = project.worklogCount ?? project._count?.worklogs ?? project.backlogCount ?? project._count?.backlogs ?? 0;
  const memberCount = project.memberCount ?? project._count?.members ?? 0;
  const milestoneCount = project.milestoneCount ?? project._count?.milestones ?? 0;
  const ownerId = project.owner?.id ?? project.ownerId ?? 0;

  return {
    ...project,
    taskCount,
    worklogCount,
    memberCount,
    milestoneCount,
    owner: project.owner ?? {
      id: ownerId,
      fullName: ownerId ? `User #${ownerId}` : "—",
      avatarUrl: null,
    },
    customerName: project.customerName ?? null,
    currency: project.currency ?? null,
    tags: project.tags ?? [],
    gapoThreadId: project.gapoThreadId ?? null,
    milestones: project.milestones ?? [],
    _count: {
      tasks: taskCount,
      worklogs: worklogCount,
      backlogs: worklogCount,
      members: memberCount,
      milestones: milestoneCount,
    },
  };
}
