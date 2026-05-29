import { apiClient } from "@/lib/apiClient";

export type AuditSource = "chat" | "cron" | "cli" | "other";

export type AuditLog = {
  id: number;
  tool: string;
  argsJson: unknown;
  resultJson: unknown | null;
  errorMessage: string | null;
  durationMs: number | null;
  correlationId: string | null;
  source: AuditSource;
  createdAt: string;
};

export type AuditListParams = {
  tool?: string;
  source?: AuditSource;
  correlationId?: string;
  hasError?: boolean;
  daysBack?: number;
  limit?: number;
  cursor?: number;
};

export type AuditStats = {
  window: { start: string; end: string; days: number };
  totals: { count: number; errorCount: number; errorRate: number };
  byTool: Array<{
    tool: string;
    count: number;
    errorCount: number;
    errorRate: number;
    p50Ms: number | null;
    p95Ms: number | null;
  }>;
  bySource: Record<string, number>;
  byDay: Array<{ day: string; count: number; errorCount: number }>;
  topCorrelations: Array<{ correlationId: string; count: number }>;
};

export async function listAudit(params: AuditListParams = {}) {
  const { data } = await apiClient.get<{
    data: AuditLog[];
    meta: { total: number; cutoff: string; nextCursor: number | null };
  }>("/agent/audit", { params });
  return data;
}

export async function fetchAuditStats(daysBack = 7) {
  const { data } = await apiClient.get<{ data: AuditStats }>("/agent/audit/stats", {
    params: { daysBack },
  });
  return data.data;
}
