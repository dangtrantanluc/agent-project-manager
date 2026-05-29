import { apiClient } from "@/lib/apiClient";
import type { MilestoneCreateInput } from "@bb-pm/shared";

export type Milestone = {
  id: number;
  name: string;
  status: string | null;
  dueDate: string | null;
  description: string | null;
  taskCount: number;
  doneCount: number;
  completionPct: number;
  projectId: number;
};

export async function listMilestones(projectId: number) {
  const { data } = await apiClient.get<{ data: Milestone[] }>(`/milestones/by-project/${projectId}`);
  return data.data;
}

export async function createMilestone(projectId: number, input: MilestoneCreateInput) {
  const { data } = await apiClient.post<{ data: Milestone }>(`/milestones/by-project/${projectId}`, input);
  return data.data;
}

export async function updateMilestone(id: number, input: Partial<MilestoneCreateInput>) {
  const { data } = await apiClient.patch<{ data: Milestone }>(`/milestones/${id}`, input);
  return data.data;
}

export async function deleteMilestone(id: number) {
  await apiClient.delete(`/milestones/${id}`);
}
