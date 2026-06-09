import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck } from "lucide-react";
import { toast } from "sonner";
import {
  fetchUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type Notification,
} from "@/features/notifications/api";
import { notificationTypeMeta, relativeTime } from "@/features/notifications/icons";

export function NotificationBell() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const prevCount = useRef<number | null>(null);

  const countQ = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: fetchUnreadCount,
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const listQ = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: () => listNotifications({ limit: 8 }),
    enabled: open,
  });

  // A4 — toast + tab title when new notifications arrive between polls.
  const count = countQ.data ?? 0;
  useEffect(() => {
    if (prevCount.current !== null && count > prevCount.current) {
      const delta = count - prevCount.current;
      toast(`Bạn có ${delta} thông báo mới`);
    }
    prevCount.current = count;
    const base = "Bluebolot Software";
    document.title = count > 0 ? `(${count}) ${base}` : base;
  }, [count]);

  // Close dropdown on outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

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
    setOpen(false);
    if (n.link) nav(n.link);
  };

  return (
    <div className="relative" ref={wrapRef}>
      <button
        className="relative rounded-md p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        onClick={() => setOpen((v) => !v)}
        title="Thông báo"
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] font-bold text-white">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <span className="text-sm font-semibold">Thông báo</span>
            {count > 0 && (
              <button
                className="flex items-center gap-1 text-xs text-brand-600 hover:underline"
                onClick={() => readAll.mutate()}
                disabled={readAll.isPending}
              >
                <CheckCheck className="h-3.5 w-3.5" /> Đánh dấu đã đọc
              </button>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {listQ.isLoading && (
              <p className="px-3 py-6 text-center text-sm text-slate-400">Đang tải…</p>
            )}
            {listQ.data?.data.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-slate-400">Chưa có thông báo</p>
            )}
            {listQ.data?.data.map((n) => {
              const { icon: Icon, className } = notificationTypeMeta(n.type);
              return (
                <button
                  key={n.id}
                  onClick={() => onItemClick(n)}
                  className={`flex w-full items-start gap-3 border-b border-slate-50 px-3 py-2.5 text-left hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50 ${
                    n.readAt ? "" : "bg-brand-50/40 dark:bg-brand-500/5"
                  }`}
                >
                  <span className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full ${className}`}>
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{n.title}</span>
                    {n.body && (
                      <span className="block truncate text-xs text-slate-500">{n.body}</span>
                    )}
                    <span className="block text-[11px] text-slate-400">{relativeTime(n.createdAt)}</span>
                  </span>
                  {!n.readAt && (
                    <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-brand-600" />
                  )}
                </button>
              );
            })}
          </div>

          <button
            className="w-full border-t border-slate-100 px-3 py-2 text-center text-xs font-medium text-brand-600 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
            onClick={() => {
              setOpen(false);
              nav("/notifications");
            }}
          >
            Xem tất cả
          </button>
        </div>
      )}
    </div>
  );
}
