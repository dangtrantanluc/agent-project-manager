import { apiClient } from "@/lib/apiClient";

export type Tag = {
  id: number;
  name: string;
  color: string;
  taskCount?: number;
  projectCount?: number;
};

export async function listTags(q?: string): Promise<Tag[]> {
  const { data } = await apiClient.get<{ data: Tag[] }>("/tags", {
    params: q ? { q } : {},
  });
  return data.data;
}

export async function createTag(input: { name: string; color?: string }): Promise<Tag> {
  const { data } = await apiClient.post<{ data: Tag }>("/tags", input);
  return data.data;
}

export async function updateTag(
  id: number,
  input: { name?: string; color?: string },
): Promise<Tag> {
  const { data } = await apiClient.patch<{ data: Tag }>(`/tags/${id}`, input);
  return data.data;
}

export async function deleteTag(id: number): Promise<void> {
  await apiClient.delete(`/tags/${id}`);
}

/** Đặt lại toàn bộ tag cho 1 task. Trả danh sách tag sau cập nhật. */
export async function setTaskTags(taskId: number, tagIds: number[]): Promise<Tag[]> {
  const { data } = await apiClient.put<{ data: Tag[] }>(`/tasks/${taskId}/tags`, { tagIds });
  return data.data;
}

/** Đặt lại toàn bộ tag cho 1 project. */
export async function setProjectTags(projectId: number, tagIds: number[]): Promise<Tag[]> {
  const { data } = await apiClient.put<{ data: Tag[] }>(`/projects/${projectId}/tags`, { tagIds });
  return data.data;
}
