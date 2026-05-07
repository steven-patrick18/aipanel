import {
  fetchEventSource,
  type EventSourceMessage,
} from "@microsoft/fetch-event-source";
import { getAccessToken } from "@/auth/store";
import { apiUrl } from "./client";

interface OpenSSEOpts {
  path: string;
  onMessage: (data: any) => void;
  onError?: (err: unknown) => void;
  onOpen?: () => void;
  signal?: AbortSignal;
}

/**
 * Subscribe to an SSE endpoint with the JWT in the Authorization header.
 * Auto-reconnects with backoff via fetchEventSource's built-in retry. Caller
 * is responsible for aborting via the AbortSignal when unmounting.
 */
export async function openSSE({
  path,
  onMessage,
  onError,
  onOpen,
  signal,
}: OpenSSEOpts): Promise<void> {
  const token = getAccessToken();
  await fetchEventSource(apiUrl(path), {
    signal,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    openWhenHidden: true,
    async onopen(response) {
      if (response.status >= 400) {
        throw new Error(`SSE failed: HTTP ${response.status}`);
      }
      onOpen?.();
    },
    onmessage(ev: EventSourceMessage) {
      if (!ev.data) return;
      try {
        onMessage(JSON.parse(ev.data));
      } catch {
        onMessage(ev.data);
      }
    },
    onerror(err) {
      onError?.(err);
      // Returning nothing → fetchEventSource retries with default backoff.
      // Returning a number sets retry interval ms; throwing aborts.
    },
  });
}
