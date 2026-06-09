import { apiClient } from "@/lib/apiClient";
import type {
  UserCreateInput,
  UserAdminUpdateInput,
  CurrencyCreateInput,
} from "@bb-pm/shared";

export type AdminUser = {
  id: number;
  email: string;
  fullName: string;
  role: "ADMIN" | "MANAGER" | "MEMBER" | "VIEWER";
  active: boolean;
  avatarUrl: string | null;
  lang: string;
  lastLoginAt: string | null;
  createdAt: string;
};

export async function listAdminUsers(params: { q?: string; role?: string; active?: boolean } = {}) {
  const { data } = await apiClient.get<{
    data: AdminUser[];
    meta: { total: number };
  }>("/admin/users", { params });
  return data;
}

export async function createAdminUser(input: UserCreateInput) {
  const { data } = await apiClient.post<{ data: AdminUser }>("/admin/users", input);
  return data.data;
}

export async function updateAdminUser(id: number, input: UserAdminUpdateInput) {
  const { data } = await apiClient.patch<{ data: AdminUser }>(`/admin/users/${id}`, input);
  return data.data;
}

// ── Gapo linking ────────────────────────────────────────────────────────────

export type GapoMap = {
  userId: number;
  email: string;
  fullName: string;
  active: boolean;
  linked: boolean;
  gapoUserId: string | null;
  gapoThreadId: string | null;
  gapoFullName: string | null;
  linkedAt: string | null;
  activeCode: string | null;
  codeExpiresAt: string | null;
};

export async function listGapoMaps(params: { q?: string } = {}) {
  const { data } = await apiClient.get<{ data: GapoMap[] }>("/admin/gapo-maps", { params });
  return data.data;
}

export type GapoLinkCode = { code: string; expiresAt: string; ttlHours: number };

export async function createGapoLinkCode(userId: number, relink = false) {
  const { data } = await apiClient.post<{ data: GapoLinkCode }>(
    `/admin/gapo-maps/${userId}/link-code`,
    null,
    { params: { relink } },
  );
  return data.data;
}

export async function unlinkGapoMap(userId: number) {
  await apiClient.delete(`/admin/gapo-maps/${userId}`);
}

export type CompanyInfo = {
  id: number;
  name: string;
  code: string | null;
  currencyId: number;
  currency: { id: number; code: string; symbol: string };
  _count: { users: number; projects: number };
};

export async function fetchCompany() {
  const { data } = await apiClient.get<{ data: CompanyInfo }>("/admin/company");
  return data.data;
}

export async function updateCompany(input: { name?: string; code?: string | null; currencyId?: number }) {
  const { data } = await apiClient.patch<{ data: CompanyInfo }>("/admin/company", input);
  return data.data;
}

export type CurrencyFull = {
  id: number;
  code: string;
  symbol: string;
  rate: string;
  _count?: { users?: number; projects: number };
};

export async function listCurrencies() {
  const { data } = await apiClient.get<{ data: CurrencyFull[] }>("/admin/currencies");
  return data.data;
}

export async function createCurrency(input: CurrencyCreateInput) {
  const { data } = await apiClient.post<{ data: CurrencyFull }>("/admin/currencies", input);
  return data.data;
}

export async function updateCurrency(id: number, input: Partial<CurrencyCreateInput>) {
  const { data } = await apiClient.patch<{ data: CurrencyFull }>(`/admin/currencies/${id}`, input);
  return data.data;
}

export async function deleteCurrency(id: number) {
  await apiClient.delete(`/admin/currencies/${id}`);
}
