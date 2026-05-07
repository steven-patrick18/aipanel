import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { Role, UserPublic } from "@/lib/types";

export function useUsers(tenantId: string | undefined) {
  return useQuery({
    queryKey: ["users", tenantId],
    queryFn: async () =>
      (await api.get<UserPublic[]>(`/tenants/${tenantId}/users`)).data,
    enabled: !!tenantId,
  });
}

export function useInviteUser(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { email: string; password: string; role: Role }) =>
      (await api.post<UserPublic>(`/tenants/${tenantId}/users`, body)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", tenantId] });
      toast.success("User invited");
    },
  });
}

export function useUpdateUserRole(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { userId: string; role: Role }) =>
      (await api.patch<UserPublic>(
        `/tenants/${tenantId}/users/${vars.userId}`,
        { role: vars.role },
      )).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", tenantId] });
      toast.success("Role updated");
    },
  });
}

export function useDeleteUser(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => {
      await api.delete(`/tenants/${tenantId}/users/${userId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", tenantId] });
      toast.success("User removed");
    },
  });
}

export interface AuditEntry {
  id: number;
  ts: string;
  user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
}

export function useAudit(
  tenantId: string | undefined,
  params: { limit?: number; offset?: number; action_prefix?: string } = {},
) {
  return useQuery({
    queryKey: ["audit", tenantId, params],
    queryFn: async () =>
      (await api.get<AuditEntry[]>(`/tenants/${tenantId}/audit`, { params })).data,
    enabled: !!tenantId,
    refetchInterval: 15_000,
  });
}
