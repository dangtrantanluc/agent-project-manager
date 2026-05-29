import { apiClient } from "@/lib/apiClient";

export type UserOption = {
  id: number;
  email: string;
  fullName: string;
  role: "ADMIN" | "MANAGER" | "MEMBER" | "VIEWER";
  avatarUrl: string | null;
  companyName?: string | null;
};

export async function listUsers() {
  const { data } = await apiClient.get<{ data: UserOption[] }>("/users");
  return data.data;
}
