export type SlashCommand = {
  name: string;
  description: string;
  example?: string;
};

export const slashCommands: SlashCommand[] = [
  { name: "/checkin", description: "Cập nhật worklog hôm nay", example: "/checkin fix bug login 1h" },
  { name: "/project", description: "Chọn project cho phiên worklog", example: "/project" },
  { name: "/report", description: "Xem báo cáo hôm nay", example: "/report" },
  { name: "/blocker", description: "Báo task đang bị vướng", example: "/blocker task API bị timeout" },
  { name: "/help", description: "Hiển thị danh sách lệnh", example: "/help" },
  { name: "/digest", description: "Daily digest: project, task mở, quá hạn, stale", example: "/digest" },
  { name: "/weekly", description: "Weekly report 7 ngày", example: "/weekly" },
  { name: "/mytasks", description: "Task đang được giao cho bạn", example: "/mytasks" },
  { name: "/overdue", description: "Task quá hạn deadline", example: "/overdue" },
  { name: "/blocked", description: "Task đang bị block", example: "/blocked" },
  { name: "/stale", description: "Task lâu chưa update", example: "/stale" },
  { name: "/projects", description: "Dự án đang active", example: "/projects" },
  { name: "/role", description: "Vai trò và quyền của bạn", example: "/role" },
  { name: "/automations", description: "Cron automations đang chạy", example: "/automations" },
];
