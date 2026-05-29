import { apiClient } from "@/lib/apiClient";
import type { MemberCreateInput } from "@bb-pm/shared";

export type Member = {
  id: number;
  projectId: number;
  userId: number;
  role: string | null;
  joinedAt: string;
  user: { id: number; fullName: string; email: string; avatarUrl: string | null; role: string };
  rates: [];
};

export async function listMembers(projectId: number) {
  const { data } = await apiClient.get<{ data: Member[] }>(`/members/by-project/${projectId}`);
  return data.data;
}

export async function createMember(projectId: number, input: MemberCreateInput) {
  const { data } = await apiClient.post<{ data: Member }>(`/members/by-project/${projectId}`, input);
  return data.data;
}

export async function updateMember(id: number, input: { role?: string | null }) {
  const { data } = await apiClient.patch<{ data: Member }>(`/members/${id}`, input);
  return data.data;
}

export async function deleteMember(id: number) {
  await apiClient.delete(`/members/${id}`);
}
