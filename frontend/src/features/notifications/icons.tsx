import { Bell, BellRing, AlertTriangle, CalendarClock, type LucideIcon } from "lucide-react";

type TypeMeta = { icon: LucideIcon; className: string };

const TYPE_META: Record<string, TypeMeta> = {
  checkin_reminder: { icon: BellRing, className: "bg-blue-100 text-blue-700" },
  checkin_missing_summary: { icon: AlertTriangle, className: "bg-amber-100 text-amber-700" },
  task_deadline: { icon: CalendarClock, className: "bg-rose-100 text-rose-700" },
};

const FALLBACK: TypeMeta = { icon: Bell, className: "bg-slate-100 text-slate-600" };

export function notificationTypeMeta(type: string): TypeMeta {
  return TYPE_META[type] ?? FALLBACK;
}

/** Short Vietnamese relative time, e.g. "5 phút trước", "2 giờ trước". */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return "vừa xong";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} phút trước`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} giờ trước`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 7) return `${diffDay} ngày trước`;
  return new Date(iso).toLocaleDateString("vi-VN");
}
