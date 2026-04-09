import { create } from "zustand";
import { apiFetch } from "../api/client";
import type { MeResponse } from "../types";

type AuthState = {
  token: string | null;
  me: MeResponse | null;
  setToken: (token: string | null) => void;
  refreshMe: () => Promise<void>;
};

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem("token"),
  me: null,
  setToken: (token) => {
    if (token) {
      localStorage.setItem("token", token);
    } else {
      localStorage.removeItem("token");
    }
    set({ token });
  },
  refreshMe: async () => {
    const me = await apiFetch<MeResponse>("/auth/me");
    set({ me });
  },
}));
