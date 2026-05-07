import { useQuery } from "@tanstack/react-query";
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
  });
}
