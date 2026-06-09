export function formatMoney(value: number | string | null | undefined, symbol = "₫") {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return "—";
  return `${n.toLocaleString("vi-VN")} ${symbol}`;
}

export function formatDate(value: string | Date | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("vi-VN");
}

export function formatHours(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return `${v.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}h`;
}

/** Số ngày tới hạn được coi là "sắp đến hạn" (cảnh báo sớm). */
const DUE_SOON_DAYS = 3;

export type DeadlineState = "overdue" | "due-soon" | "normal";

/**
 * Trạng thái deadline của một task (để tô màu cột Deadline).
 *  - overdue : đã quá hạn (deadline < hôm nay)
 *  - due-soon: sắp đến hạn (hôm nay .. +3 ngày)
 *  - normal  : còn xa / không có deadline / task đã Xong|Hủy
 * Task đã DONE/CANCELLED không cảnh báo (đã xong, hạn không còn ý nghĩa).
 */
export function deadlineState(
  deadline: string | null | undefined,
  status?: string,
): DeadlineState {
  if (!deadline) return "normal";
  if (status === "DONE" || status === "CANCELLED") return "normal";

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(deadline);
  due.setHours(0, 0, 0, 0);

  const diffDays = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (diffDays < 0) return "overdue";
  if (diffDays <= DUE_SOON_DAYS) return "due-soon";
  return "normal";
}

/** Class Tailwind cho text deadline theo trạng thái (đỏ-đậm quá hạn, hổ phách sắp tới). */
export const deadlineTextClass: Record<DeadlineState, string> = {
  overdue: "font-semibold text-rose-600 dark:text-rose-400",
  "due-soon": "text-amber-600 dark:text-amber-400",
  normal: "",
};

/** Class nền cho CẢ HÀNG task theo trạng thái deadline (kèm hover đậm hơn). */
export const deadlineRowClass: Record<DeadlineState, string> = {
  overdue: "bg-rose-50 hover:bg-rose-100 dark:bg-rose-950/30 dark:hover:bg-rose-950/50",
  "due-soon": "bg-amber-50 hover:bg-amber-100 dark:bg-amber-950/30 dark:hover:bg-amber-950/50",
  normal: "",
};

export const statusColors: Record<string, string> = {
  TODO: "bg-slate-100 text-slate-700",
  PLANNED: "bg-slate-100 text-slate-700",
  PENDING: "bg-amber-100 text-amber-700",
  IN_PROGRESS: "bg-blue-100 text-blue-700",
  CANCELLED: "bg-rose-100 text-rose-700",
  DONE: "bg-emerald-100 text-emerald-700",
  APPROVED: "bg-emerald-100 text-emerald-700",
  REJECTED: "bg-rose-100 text-rose-700",
};

export const priorityColors: Record<string, string> = {
  LOW: "bg-slate-100 text-slate-700",
  MEDIUM: "bg-blue-100 text-blue-700",
  HIGH: "bg-orange-100 text-orange-700",
  URGENT: "bg-rose-100 text-rose-700",
};

export const statusLabels: Record<string, string> = {
  TODO: "Cần làm",
  PLANNED: "Cần làm",
  PENDING: "Tạm dừng",
  IN_PROGRESS: "Đang triển khai",
  CANCELLED: "Đã hủy",
  DONE: "Xong",
  APPROVED: "Đã duyệt",
  REJECTED: "Từ chối",
};
