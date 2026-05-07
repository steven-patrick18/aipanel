import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { TokenPair, UserPublic } from "@/lib/types";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  accessExpiresAt: string | null;
  user: UserPublic | null;
  setSession: (tokens: TokenPair, user: UserPublic) => void;
  setTokens: (tokens: TokenPair) => void;
  setUser: (user: UserPublic) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      accessExpiresAt: null,
      user: null,

      setSession: (tokens, user) =>
        set({
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          accessExpiresAt: tokens.access_expires_at,
          user,
        }),

      setTokens: (tokens) =>
        set({
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          accessExpiresAt: tokens.access_expires_at,
        }),

      setUser: (user) => set({ user }),

      clear: () =>
        set({
          accessToken: null,
          refreshToken: null,
          accessExpiresAt: null,
          user: null,
        }),
    }),
    {
      name: "aipanel-auth",
      storage: createJSONStorage(() => localStorage),
    }
  )
);

/**
 * Read the current access token without subscribing to changes — used by the
 * axios interceptor and the SSE wrapper, both of which run outside React.
 */
export const getAccessToken = (): string | null =>
  useAuth.getState().accessToken;
