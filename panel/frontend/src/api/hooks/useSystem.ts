import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { NodeRow, SafeConfig, SystemHealth } from "@/lib/types";

export function useSystemHealth() {
  return useQuery({
    queryKey: ["system", "health"],
    queryFn: async () => (await api.get<SystemHealth>("/system/health")).data,
    refetchInterval: 15_000,
  });
}

export function useSystemVersion() {
  return useQuery({
    queryKey: ["system", "version"],
    queryFn: async () => (await api.get<{ version: string }>("/system/version")).data,
  });
}

export function useSafeConfig() {
  return useQuery({
    queryKey: ["system", "config"],
    queryFn: async () => (await api.get<SafeConfig>("/system/config")).data,
  });
}

export function useNodes() {
  return useQuery({
    queryKey: ["cluster", "nodes"],
    queryFn: async () => (await api.get<NodeRow[]>("/cluster/nodes")).data,
    refetchInterval: 5_000,
  });
}

// ---------------------------------------------------------------------------
// Cluster — join tokens + node lifecycle
// ---------------------------------------------------------------------------

export type NodeRole = "primary" | "secondary" | "gpu" | "app" | "sip" | "mixed";

export interface JoinToken {
  id: string;
  role: NodeRole;
  label: string;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
}

export interface JoinTokenCreated extends JoinToken {
  token: string;
  install_command: string;
}

export function useJoinTokens() {
  return useQuery({
    queryKey: ["cluster", "join-tokens"],
    queryFn: async () =>
      (await api.get<JoinToken[]>("/cluster/join-tokens")).data,
    refetchInterval: 30_000,
  });
}

export function useCreateJoinToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      role: NodeRole;
      label?: string;
      ttl_minutes?: number;
    }) =>
      (await api.post<JoinTokenCreated>("/cluster/join-tokens", vars)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cluster", "join-tokens"] });
    },
  });
}

export function useRevokeJoinToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/cluster/join-tokens/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cluster", "join-tokens"] });
      toast.success("Token revoked");
    },
  });
}

export function useDrainNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (nodeId: string) =>
      (await api.post(`/cluster/nodes/${nodeId}/drain`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cluster", "nodes"] });
      toast.success("Draining — finishing in-flight calls then shutting down");
    },
  });
}

export function useRemoveNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (nodeId: string) => {
      await api.delete(`/cluster/nodes/${nodeId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cluster", "nodes"] });
      toast.success("Node removed");
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Could not remove node");
    },
  });
}

export function useUpdateNodeRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { nodeId: string; role: NodeRole }) =>
      (await api.patch(`/cluster/nodes/${vars.nodeId}`, { role: vars.role })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cluster", "nodes"] });
      toast.success("Role updated");
    },
  });
}

// Mock-only: simulate a real node phoning home with the token.
// Real install.sh hits POST /api/v1/cluster/join.
export function useMockSimulateJoin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (token: string) =>
      (await api.post("/cluster/_mock-simulate-join", { token })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cluster", "nodes"] });
    },
  });
}
