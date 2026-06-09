import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCheck } from "lucide-react";
import { toast } from "sonner";
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type Notification,
} from "@/features/notifications/api";
import { notificationTypeMeta, relativeTime } from "@/features/notifications/icons";

const FILTERS: Array<{ key: "all" | "unread"; label: string }> = [
  { key: "all", label: "Tất cả" },
  { key: "unread", label: "Chưa đọc" },
];

export function NotificationsPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [filter, setFilter] = useState<"all" | "unread">("all");

  const q = useQuery({
    queryKey: ["notifications", "page", filter],
    queryFn: () => listNotifications({ limit: 50, unread: filter === "unread" || undefined }),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["notifications"] });

  const readOne = useMutation({
    mutationFn: (id: number) => markNotificationRead(id),
    onSuccess: invalidate,
  });

  const readAll = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      invalidate();
      toast.success("Đã đánh dấu tất cả là đã đọc");
    },
  });

  const onItemClick = (n: Notification) => {
    if (!n.readAt) readOne.mutate(n.id);
    if (n.link) nav(n.link);
  };

  const items = q.data?.data ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Thông báo</h1>
        <button
          className="flex items-center gap-1 text-sm text-brand-600 hover:underline disabled:opacity-50"
          onClick={() => readAll.mutate()}
          disabled={readAll.isPending}
        >
          <CheckCheck className="h-4 w-4" /> Đánh dấu tất cả đã đọc
        </button>
      </div>

      <div className="flex gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-md px-3 py-1.5 text-sm ${
              filter === f.key
                ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400"
                : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
        {q.isLoading && <p className="px-4 py-8 text-center text-sm text-slate-400">Đang tải…</p>}
        {!q.isLoading && items.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-slate-400">Không có thông báo</p>
        )}
        {items.map((n) => {
          const { icon: Icon, className } = notificationTypeMeta(n.type);
          return (
            <button
              key={n.id}
              onClick={() => onItemClick(n)}
              className={`flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                n.readAt ? "" : "bg-brand-50/40 dark:bg-brand-500/5"
              }`}
            >
              <span className={`mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full ${className}`}>
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{n.title}</span>
                {n.body && <span className="block text-sm text-slate-500">{n.body}</span>}
                <span className="block text-xs text-slate-400">{relativeTime(n.createdAt)}</span>
              </span>
              {!n.readAt && <span className="mt-2 h-2 w-2 flex-shrink-0 rounded-full bg-brand-600" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
