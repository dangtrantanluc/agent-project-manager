import axios from "axios";
import { useAuth } from "@/features/auth/store";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? "/api/v1",
});

apiClient.interceptors.request.use((config) => {
  const token = useAuth.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (config.data instanceof FormData) {
    delete config.headers["content-type"];
    delete config.headers["Content-Type"];
  }
  return config;
});

// Token hết hạn / không hợp lệ → xoá auth và đưa về trang đăng nhập.
// Chỉ xử lý khi đang có token (tránh redirect vòng lặp ngay tại trang login).
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && useAuth.getState().accessToken) {
      useAuth.getState().clear();
      if (window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);
