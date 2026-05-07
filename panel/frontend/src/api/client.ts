import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { toast } from "sonner";
import { getAccessToken, useAuth } from "@/auth/store";

const BASE_URL = import.meta.env.VITE_API_URL ?? "/api/v1";

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
});

// ---------------------------------------------------------------------------
// Request: inject JWT
// ---------------------------------------------------------------------------

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------------------------------------------------------------------------
// Response: refresh-once on 401, then redirect
// ---------------------------------------------------------------------------

let refreshing: Promise<string | null> | null = null;

async function tryRefresh(): Promise<string | null> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const refreshToken = useAuth.getState().refreshToken;
    if (!refreshToken) return null;
    try {
      const response = await axios.post(
        `${BASE_URL}/auth/refresh`,
        { refresh_token: refreshToken },
        { timeout: 10_000 },
      );
      useAuth.getState().setTokens(response.data);
      return response.data.access_token as string;
    } catch {
      useAuth.getState().clear();
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // Auth errors → refresh + retry once.
    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes("/auth/")
    ) {
      original._retry = true;
      const fresh = await tryRefresh();
      if (fresh) {
        original.headers = original.headers ?? {};
        (original.headers as Record<string, string>).Authorization = `Bearer ${fresh}`;
        return api(original);
      }
      // Refresh failed — kick to /login. Don't toast (the redirect tells the story).
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
      return Promise.reject(error);
    }

    // Surface server-side errors as toasts. Skip for known noisy paths.
    const detail =
      (error.response?.data as any)?.detail ||
      error.message ||
      "Request failed";
    if (!original?.url?.endsWith("/health")) {
      toast.error(typeof detail === "string" ? detail : "Request failed");
    }
    return Promise.reject(error);
  },
);

/**
 * Build the absolute URL for things that bypass axios (SSE, anchor downloads).
 */
export const apiUrl = (path: string): string => {
  if (path.startsWith("http")) return path;
  return `${BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
};
