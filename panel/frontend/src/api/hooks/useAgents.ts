import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { Agent, Page } from "@/lib/types";

interface AgentListParams {
  limit?: number;
  offset?: number;
  status?: string;
  name_contains?: string;
}

export function useAgents(params: AgentListParams = {}) {
  return useQuery({
    queryKey: ["agents", params],
    queryFn: async () => {
      const r = await api.get<Page<Agent>>("/agents", { params });
      return r.data;
    },
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: ["agents", id],
    queryFn: async () => {
      const r = await api.get<Agent>(`/agents/${id}`);
      return r.data;
    },
    enabled: !!id,
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: any) => {
      const r = await api.post<Agent>("/agents", body);
      return r.data;
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success(`Created agent "${data.name}"`);
    },
  });
}

export function useUpdateAgent(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: any) => {
      const r = await api.patch<Agent>(`/agents/${id}`, body);
      return r.data;
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.setQueryData(["agents", id], data);
      toast.success("Saved");
    },
  });
}

export function useArchiveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/agents/${id}`);
      return id;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agent archived");
    },
  });
}

export function useDuplicateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await api.post<Agent>(`/agents/${id}/duplicate`);
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Duplicated");
    },
  });
}

export function usePromoteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await api.post<Agent>(`/agents/${id}/promote`);
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Promoted to ready");
    },
  });
}

export function useTestCall(agentId: string) {
  return useMutation({
    mutationFn: async (vars: { phone_number: string; deployment_id?: string }) => {
      await api.post(`/agents/${agentId}/test-call`, vars);
    },
    onSuccess: () => {
      toast.success("Dialing — check your softphone");
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail || "Test call failed";
      toast.error(msg);
    },
  });
}
