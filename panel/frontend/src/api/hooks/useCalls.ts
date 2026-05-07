import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { CallEvent, CallSummary, CallTranscript, Page } from "@/lib/types";

export interface CallFilters {
  limit?: number;
  offset?: number;
  deployment_id?: string;
  outcome?: string;
  started_after?: string;
  started_before?: string;
}

export function useCalls(filters: CallFilters = {}) {
  return useQuery({
    queryKey: ["calls", filters],
    queryFn: async () =>
      (await api.get<Page<CallSummary>>("/calls", { params: filters })).data,
  });
}

export function useCall(id: string | undefined) {
  return useQuery({
    queryKey: ["calls", id],
    queryFn: async () => (await api.get<CallSummary>(`/calls/${id}`)).data,
    enabled: !!id,
  });
}

export function useCallTranscript(id: string | undefined) {
  return useQuery({
    queryKey: ["calls", id, "transcript"],
    queryFn: async () => (await api.get<CallTranscript>(`/calls/${id}/transcript`)).data,
    enabled: !!id,
  });
}

export function useCallEvents(id: string | undefined) {
  return useQuery({
    queryKey: ["calls", id, "events"],
    queryFn: async () => (await api.get<CallEvent[]>(`/calls/${id}/events`)).data,
    enabled: !!id,
  });
}

export function useCallRecording(id: string | undefined) {
  return useQuery({
    queryKey: ["calls", id, "recording"],
    queryFn: async () =>
      (await api.get<{ url: string; expires_in: number }>(`/calls/${id}/recording`)).data,
    enabled: !!id,
    retry: false,
  });
}

export interface IngroupOption { id: string; label: string; }

export function useTransferOptions(callId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["calls", callId, "transfer-options"],
    queryFn: async () =>
      (await api.get<IngroupOption[]>(`/calls/${callId}/transfer-options`)).data,
    enabled: !!callId && enabled,
  });
}

export function useTransferCall(callId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { ingroup_id: string; summary?: string }) => {
      await api.post(`/calls/${callId}/transfer`, vars);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calls", callId] });
      qc.invalidateQueries({ queryKey: ["calls", callId, "events"] });
      toast.success("Transfer requested — ViciDial is bridging the call now");
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail || "Transfer failed";
      toast.error(msg);
    },
  });
}
