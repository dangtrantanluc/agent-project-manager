import { useQuery } from "@tanstack/react-query";

import { getTaskActivity } from "@/features/tasks/api";
import { formatDateTime } from "@/lib/format";

const _SOURCE_LABEL: Record<string, string> = {
  chat: "Chat", web: "Web", system: "Hệ thống", cron: "Tự động", cli: "CLI", other: "Khác",
};

/**
 * Dòng thời gian hoạt động của task (mới nhất trên đầu): đổi %/status, ghi kết quả/
 * khó khăn, tạo/gỡ blocker. Lazy — chỉ fetch khi `enabled` (section mở rộng).
 */
export function TaskActivityTimeline({ taskId, enabled }: { taskId: number; enabled: boolean }) {
  const q = useQuery({
    queryKey: ["task-activity", taskId],
    queryFn: () => getTaskActivity(taskId),
    enabled,
  });

  if (q.isLoading) return <p className="py-2 text-xs text-slate-400">Đang tải lịch sử…</p>;
  if (q.isError) return <p className="py-2 text-xs text-red-500">Không tải được lịch sử.</p>;
  const events = q.data?.events ?? [];
  if (events.length === 0) return <p className="py-2 text-xs text-slate-400">Chưa có hoạt động nào.</p>;

  return (
    <ul className="space-y-2">
      {events.map((e, i) => (
        <li key={i} className="flex gap-2 text-xs">
          <span className="shrink-0">{e.icon}</span>
          <div className="min-w-0">
            <div className="whitespace-pre-wrap break-words text-slate-700 dark:text-slate-200">{e.summary}</div>
            <div className="text-slate-400">
              🕒 {formatDateTime(e.at)}
              {e.actor && <span> · {e.actor}</span>}
              <span className="ml-1 rounded bg-slate-100 px-1 dark:bg-slate-800">
                {_SOURCE_LABEL[e.source] ?? e.source}
              </span>
            </div>
          </div>
        </li>
      ))}
      {q.data?.truncated && (
        <li className="text-xs text-slate-400">… chỉ hiển thị {events.length} sự kiện gần nhất.</li>
      )}
    </ul>
  );
}
