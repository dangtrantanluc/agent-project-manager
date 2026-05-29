import { apiClient } from "@/lib/apiClient";
import type { MeUpdateInput } from "@bb-pm/shared";

export async function updateMe(input: MeUpdateInput) {
  const { data } = await apiClient.patch<{ data: any }>("/me", input);
  return data.data;
}

export async function uploadAvatar(file: File) {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await apiClient.post<{ data: { avatarUrl: string } }>("/uploads/avatar", fd, {
    headers: { "content-type": "multipart/form-data" },
  });
  return data.data.avatarUrl;
}
