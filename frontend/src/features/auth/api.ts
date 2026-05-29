import { apiClient } from "@/lib/apiClient";
import type { LoginInput, RegisterInput } from "@bb-pm/shared";
import type { AuthUser } from "./store";

type AuthResponse = {
  user: AuthUser;
  accessToken: string;
};

export async function login(input: LoginInput) {
  const { data } = await apiClient.post<AuthResponse>("/auth/login", input);
  return data;
}

export async function register(input: RegisterInput) {
  const { data } = await apiClient.post<AuthResponse>("/auth/register", input);
  return data;
}

export async function fetchMe() {
  const { data } = await apiClient.get<AuthUser>("/me");
  return data;
}
