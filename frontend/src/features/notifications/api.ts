import { apiClient } from "@/lib/apiClient";

export type Notification = {
  id: number;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  readAt: string | null;
  createdAt: string;
};

export type NotificationListParams = {
  unread?: boolean;
  limit?: number;
  cursor?: number;
};

export async function listNotifications(params: NotificationListParams = {}) {
  const { data } = await apiClient.get<{
    data: Notification[];
    meta: { nextCursor: number | null };
  }>("/notifications", { params });
  return data;
}

export async function fetchUnreadCount() {
  const { data } = await apiClient.get<{ data: { count: number } }>(
    "/notifications/unread-count",
  );
  return data.data.count;
}

export async function markNotificationRead(id: number) {
  const { data } = await apiClient.patch<{ data: { id: number } }>(
    `/notifications/${id}/read`,
  );
  return data.data;
}

export async function markAllNotificationsRead() {
  const { data } = await apiClient.post<{ data: { updated: number } }>(
    "/notifications/read-all",
  );
  return data.data;
}
