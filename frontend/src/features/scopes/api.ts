import { apiClient } from "@/lib/apiClient";
import type { ScopeCreateInput } from "@bb-pm/shared";

export type Scope = {
  id: number;
  sequence: number;
  name: string;
  notes: string | null;
  estimatedHours: string | null;
  projectId: number;
  taskId: number | null;
  assigneeId: number | null;
  currencyId: number | null;
  task: { id: number; name: string; status: string } | null;
  assignee: { id: number; fullName: string } | null;
  currency: { id: number; code: string; symbol: string } | null;
};

export async function listScopes(projectId: number) {
  const { data } = await apiClient.get<{ data: Scope[] }>(`/scopes/by-project/${projectId}`);
  return data.data;
}

export async function createScope(projectId: number, input: ScopeCreateInput) {
  const { data } = await apiClient.post<{ data: Scope }>(`/scopes/by-project/${projectId}`, input);
  return data.data;
}

export async function updateScope(id: number, input: Partial<ScopeCreateInput>) {
  const { data } = await apiClient.patch<{ data: Scope }>(`/scopes/${id}`, input);
  return data.data;
}

export async function deleteScope(id: number) {
  await apiClient.delete(`/scopes/${id}`);
}

export async function reorderScopes(projectId: number, orderedIds: number[]) {
  await apiClient.post(`/scopes/by-project/${projectId}/reorder`, { orderedIds });
}
