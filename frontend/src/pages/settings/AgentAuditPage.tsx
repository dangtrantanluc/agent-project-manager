import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Clock,
  Search,
  Filter,
  ChevronRight,
  X,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Modal } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import {
  fetchAuditStats,
  listAudit,
  type AuditLog,
  type AuditSource,
} from "@/features/agent-audit/api";

const SOURCE_COLORS: Record<string, string> = {
  chat: "bg-blue-100 text-blue-700",
  cron: "bg-violet-100 text-violet-700",
  cli: "bg-slate-100 text-slate-700",
  other: "bg-slate-100 text-slate-500",
};

function fmtMs(ms: number | null | undefined) {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function fmtDateTime(s: string) {
  return new Date(s).toLocaleString("vi-VN", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function AgentAuditPage() {
  const [daysBack, setDaysBack] = useState(7);
  const [tool, setTool] = useState("");
  const [source, setSource] = useState<AuditSource | "">("");
  const [correlationId, setCorrelationId] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [selected, setSelected] = useState<AuditLog | null>(null);
  const [timelineCorrelation, setTimelineCorrelation] = useState<string | null>(null);

  const statsQ = useQuery({
    queryKey: ["agent-audit-stats", daysBack],
    queryFn: () => fetchAuditStats(daysBack),
    refetchInterval: 30_000,
  });

  const listQ = useQuery({
    queryKey: ["agent-audit-list", daysBack, tool, source, correlationId, errorsOnly],
    queryFn: () =>
      listAudit({
        daysBack,
        tool: tool || undefined,
        source: (source as AuditSource) || undefined,
        correlationId: correlationId || undefined,
        hasError: errorsOnly ? true : undefined,
        limit: 100,
      }),
    refetchInterval: 30_000,
  });

  const errorRatePct = useMemo(
    () => ((statsQ.data?.totals.errorRate ?? 0) * 100).toFixed(1),
    [statsQ.data],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Agent audit log</h2>
          <p className="text-sm text-slate-500">
            Mọi tool call của PM Agent (overdue, follow-up, blocker…) — debug + giám sát.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Window:</span>
          {[1, 7, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDaysBack(d)}
              className={`rounded px-3 py-1 text-sm ${
                daysBack === d
                  ? "bg-brand-600 text-white"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              }`}
            >
              {d === 1 ? "24h" : `${d}d`}
            </button>
          ))}
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          icon={<Activity className="h-4 w-4 text-blue-600" />}
          label="Tổng tool call"
          value={statsQ.data?.totals.count?.toLocaleString("vi-VN") ?? "…"}
        />
        <KpiCard
          icon={<AlertTriangle className="h-4 w-4 text-rose-600" />}
          label="Tỷ lệ lỗi"
          value={`${errorRatePct}%`}
          sub={`${statsQ.data?.totals.errorCount ?? 0} lỗi`}
          tone={Number(errorRatePct) > 5 ? "warn" : "ok"}
        />
        <KpiCard
          icon={<Clock className="h-4 w-4 text-violet-600" />}
          label="Tool top traffic"
          value={statsQ.data?.byTool[0]?.tool ?? "—"}
          sub={`${statsQ.data?.byTool[0]?.count ?? 0} calls`}
        />
        <KpiCard
          icon={<Filter className="h-4 w-4 text-emerald-600" />}
          label="Sources"
          value={
            statsQ.data
              ? Object.entries(statsQ.data.bySource)
                  .filter(([, v]) => v > 0)
                  .map(([k, v]) => `${k}:${v}`)
                  .join(" · ")
              : "…"
          }
        />
      </div>

      {/* Daily volume chart */}
      <div className="card p-4">
        <div className="mb-2 text-sm font-medium">Volume theo ngày</div>
        <div className="h-48">
          {statsQ.data?.byDay && statsQ.data.byDay.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statsQ.data.byDay} barCategoryGap={6}>
                <XAxis dataKey="day" fontSize={11} />
                <YAxis fontSize={11} />
                <Tooltip />
                <Legend />
                <Bar dataKey="count" name="Tổng" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                <Bar dataKey="errorCount" name="Lỗi" fill="#f43f5e" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              {statsQ.isLoading ? "Đang tải…" : "Chưa có dữ liệu"}
            </div>
          )}
        </div>
      </div>

      {/* Per-tool stats */}
      <div className="card p-0">
        <div className="border-b border-slate-200 p-3 text-sm font-medium dark:border-slate-800">
          Per-tool stats
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left dark:bg-slate-800/50">
              <tr>
                <th className="p-2.5">Tool</th>
                <th className="p-2.5 text-right">Calls</th>
                <th className="p-2.5 text-right">p50</th>
                <th className="p-2.5 text-right">p95</th>
                <th className="p-2.5 text-right">Lỗi</th>
                <th className="p-2.5 text-right">Error rate</th>
              </tr>
            </thead>
            <tbody>
              {statsQ.data?.byTool.map((t) => (
                <tr
                  key={t.tool}
                  className="cursor-pointer border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                  onClick={() => setTool(t.tool)}
                >
                  <td className="p-2.5 font-mono text-xs">{t.tool}</td>
                  <td className="p-2.5 text-right">{t.count}</td>
                  <td className="p-2.5 text-right text-slate-500">{fmtMs(t.p50Ms)}</td>
                  <td className="p-2.5 text-right text-slate-500">{fmtMs(t.p95Ms)}</td>
                  <td className="p-2.5 text-right">
                    {t.errorCount > 0 ? (
                      <span className="text-rose-600">{t.errorCount}</span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="p-2.5 text-right">
                    <span
                      className={
                        t.errorRate > 0.05
                          ? "text-rose-600"
                          : t.errorRate > 0
                          ? "text-amber-600"
                          : "text-slate-400"
                      }
                    >
                      {(t.errorRate * 100).toFixed(1)}%
                    </span>
                  </td>
                </tr>
              ))}
              {statsQ.data?.byTool.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-6 text-center text-sm text-slate-400">
                    Chưa có tool call nào trong window
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Top correlations (noisy threads) */}
      {statsQ.data?.topCorrelations && statsQ.data.topCorrelations.length > 0 && (
        <div className="card p-4">
          <div className="mb-2 text-sm font-medium">Top correlations (cuộc hội thoại nhiều tool call nhất)</div>
          <div className="space-y-1.5 text-sm">
            {statsQ.data.topCorrelations.map((c) => (
              <button
                key={c.correlationId}
                onClick={() => setTimelineCorrelation(c.correlationId)}
                className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50"
              >
                <span className="font-mono text-xs text-slate-600">{c.correlationId}</span>
                <span className="flex items-center gap-2 text-slate-500">
                  <span>{c.count} calls</span>
                  <ChevronRight className="h-3.5 w-3.5" />
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Filter row */}
      <div className="card p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input w-48 pl-8"
              placeholder="Tool name…"
              value={tool}
              onChange={(e) => setTool(e.target.value)}
            />
          </div>
          <select
            className="input w-32"
            value={source}
            onChange={(e) => setSource(e.target.value as AuditSource | "")}
          >
            <option value="">All sources</option>
            <option value="chat">chat</option>
            <option value="cron">cron</option>
            <option value="cli">cli</option>
            <option value="other">other</option>
          </select>
          <input
            className="input w-64"
            placeholder="Correlation id…"
            value={correlationId}
            onChange={(e) => setCorrelationId(e.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={errorsOnly}
              onChange={(e) => setErrorsOnly(e.target.checked)}
            />
            Errors only
          </label>
          {(tool || source || correlationId || errorsOnly) && (
            <button
              className="btn-ghost border border-slate-200 px-2 py-1 text-xs"
              onClick={() => {
                setTool("");
                setSource("");
                setCorrelationId("");
                setErrorsOnly(false);
              }}
            >
              <X className="mr-1 inline h-3 w-3" /> Clear
            </button>
          )}
        </div>
      </div>

      {/* Audit log table */}
      <div className="card p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left dark:bg-slate-800/50">
              <tr>
                <th className="p-2.5">Khi</th>
                <th className="p-2.5">Tool</th>
                <th className="p-2.5">Source</th>
                <th className="p-2.5 text-right">Duration</th>
                <th className="p-2.5">Correlation</th>
                <th className="p-2.5">Trạng thái</th>
              </tr>
            </thead>
            <tbody>
              {listQ.data?.data.map((row) => (
                <tr
                  key={row.id}
                  className="cursor-pointer border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                  onClick={() => setSelected(row)}
                >
                  <td className="p-2.5 text-xs text-slate-500">{fmtDateTime(row.createdAt)}</td>
                  <td className="p-2.5 font-mono text-xs">{row.tool}</td>
                  <td className="p-2.5">
                    <Badge className={SOURCE_COLORS[row.source]}>{row.source}</Badge>
                  </td>
                  <td className="p-2.5 text-right text-slate-500">{fmtMs(row.durationMs)}</td>
                  <td className="p-2.5">
                    {row.correlationId ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setTimelineCorrelation(row.correlationId);
                        }}
                        className="font-mono text-xs text-blue-600 hover:underline"
                      >
                        {row.correlationId.slice(0, 16)}…
                      </button>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                  <td className="p-2.5">
                    {row.errorMessage ? (
                      <Badge className="bg-rose-100 text-rose-700">error</Badge>
                    ) : (
                      <Badge className="bg-emerald-100 text-emerald-700">ok</Badge>
                    )}
                  </td>
                </tr>
              ))}
              {listQ.data?.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-6 text-center text-sm text-slate-400">
                    Không có entry nào khớp filter
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AuditDetailModal row={selected} onClose={() => setSelected(null)} />
      <TimelineModal
        correlationId={timelineCorrelation}
        onClose={() => setTimelineCorrelation(null)}
        onPickRow={(r) => setSelected(r)}
      />
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
  sub,
  tone = "ok",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="card p-4">
      <div className="mb-1 flex items-center gap-2 text-xs font-medium text-slate-500">
        {icon}
        {label}
      </div>
      <div
        className={`text-xl font-semibold ${tone === "warn" ? "text-rose-600" : "text-slate-900 dark:text-slate-100"}`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

function AuditDetailModal({ row, onClose }: { row: AuditLog | null; onClose: () => void }) {
  if (!row) return null;
  return (
    <Modal open={!!row} onClose={onClose} title={`${row.tool} · #${row.id}`} size="lg">
      <div className="space-y-3 text-sm">
        <DetailRow label="Khi" value={fmtDateTime(row.createdAt)} />
        <DetailRow label="Source" value={row.source} />
        <DetailRow label="Duration" value={fmtMs(row.durationMs)} />
        <DetailRow label="Correlation" value={row.correlationId ?? "—"} mono />
        {row.errorMessage && (
          <div>
            <div className="mb-1 text-xs font-medium text-rose-700">Error</div>
            <pre className="overflow-x-auto rounded bg-rose-50 p-2 text-xs text-rose-700 dark:bg-rose-900/20">
              {row.errorMessage}
            </pre>
          </div>
        )}
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">Args</div>
          <pre className="max-h-48 overflow-auto rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/50">
            {JSON.stringify(row.argsJson, null, 2)}
          </pre>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">Result</div>
          <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/50">
            {row.resultJson ? JSON.stringify(row.resultJson, null, 2) : "—"}
          </pre>
        </div>
      </div>
    </Modal>
  );
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-3">
      <div className="w-24 text-xs text-slate-500">{label}</div>
      <div className={`text-sm ${mono ? "font-mono text-xs" : ""}`}>{value}</div>
    </div>
  );
}

function TimelineModal({
  correlationId,
  onClose,
  onPickRow,
}: {
  correlationId: string | null;
  onClose: () => void;
  onPickRow: (r: AuditLog) => void;
}) {
  const q = useQuery({
    queryKey: ["agent-audit-timeline", correlationId],
    queryFn: () => listAudit({ correlationId: correlationId!, daysBack: 30, limit: 200 }),
    enabled: !!correlationId,
  });
  if (!correlationId) return null;

  // Show oldest first for a real timeline read
  const rows = (q.data?.data ?? []).slice().sort((a, b) => a.id - b.id);

  return (
    <Modal
      open={!!correlationId}
      onClose={onClose}
      title={`Timeline: ${correlationId.slice(0, 32)}${correlationId.length > 32 ? "…" : ""}`}
      size="lg"
    >
      {q.isLoading ? (
        <div className="p-4 text-sm text-slate-400">Đang tải…</div>
      ) : rows.length === 0 ? (
        <div className="p-4 text-sm text-slate-400">Không tìm thấy entry nào</div>
      ) : (
        <div className="space-y-1.5">
          {rows.map((r, i) => (
            <button
              key={r.id}
              className="flex w-full items-start gap-3 rounded p-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50"
              onClick={() => onPickRow(r)}
            >
              <div className="w-6 text-right text-xs text-slate-400">{i + 1}.</div>
              <div className="flex-1">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-xs">{r.tool}</span>
                  {r.errorMessage ? (
                    <Badge className="bg-rose-100 text-rose-700">error</Badge>
                  ) : null}
                  <span className="ml-auto text-xs text-slate-400">
                    {fmtDateTime(r.createdAt)} · {fmtMs(r.durationMs)}
                  </span>
                </div>
                {r.errorMessage && (
                  <div className="mt-0.5 truncate text-xs text-rose-600">{r.errorMessage}</div>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}
