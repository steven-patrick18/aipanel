import { useMutation } from "@tanstack/react-query";
import { api } from "../client";
import { useAuth as useAuthStore } from "@/auth/store";
import type { LoginResponse } from "@/lib/types";

export function useLogin() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: async (input: { email: string; password: string }) => {
      const r = await api.post<LoginResponse>("/auth/login", input);
      return r.data;
    },
    onSuccess: (data) => {
      setSession(data.tokens, data.user);
    },
  });
}

export function useLogout() {
  const clear = useAuthStore((s) => s.clear);
  return useMutation({
    mutationFn: async () => {
      try {
        await api.post("/auth/logout");
      } catch {
        // logout is best-effort; clear locally regardless.
      }
    },
    onSettled: () => {
      clear();
      window.location.href = "/login";
    },
  });
}
