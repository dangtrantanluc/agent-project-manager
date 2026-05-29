import { create } from "zustand";
import { persist } from "zustand/middleware";

export type AuthUser = {
  id: number;
  email: string;
  fullName: string;
  role: "ADMIN" | "MANAGER" | "MEMBER" | "VIEWER";
  companyName?: string | null;
  isSuperAdmin: boolean;
  avatarUrl?: string | null;
  lang?: string;
};

type State = {
  accessToken: string | null;
  user: AuthUser | null;
  setToken: (access: string) => void;
  setUser: (u: AuthUser) => void;
  clear: () => void;
};

export const useAuth = create<State>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      setToken: (accessToken) => set({ accessToken }),
      setUser: (user) => set({ user }),
      clear: () => set({ accessToken: null, user: null }),
    }),
    { name: "bb-pm-auth" },
  ),
);
