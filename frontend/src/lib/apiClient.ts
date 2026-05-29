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
