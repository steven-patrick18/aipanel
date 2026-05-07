import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { Deployment, Page } from "@/lib/types";

export function useDeployments(status?: string) {
  return useQuery({
    queryKey: ["deployments", status],
    queryFn: async () =>
      (await api.get<Page<Deployment>>("/deployments", { params: { status } })).data,
    refetchInterval: 10_000,
  });
}

export function useDeployment(id: string | undefined) {
  return useQuery({
    queryKey: ["deployments", id],
    queryFn: async () => (await api.get<Deployment>(`/deployments/${id}`)).data,
    enabled: !!id,
    refetchInterval: 5_000,
  });
}

export function useCreateDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: any) => {
      const r = await api.post<Deployment>("/deployments", body);
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deployments"] });
      toast.success("Deployment created");
    },
  });
}

export function useDeploymentControl(id: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["deployments"] });

  return {
    start: useMutation({
      mutationFn: async () => (await api.post(`/deployments/${id}/start`)).data,
      onSuccess: () => { invalidate(); toast.success("Starting…"); },
    }),
    stop: useMutation({
      mutationFn: async () => (await api.post(`/deployments/${id}/stop`)).data,
      onSuccess: () => { invalidate(); toast.success("Stopping…"); },
    }),
    pause: useMutation({
      mutationFn: async (pause_code: string) =>
        (await api.post(`/deployments/${id}/pause`, null, { params: { pause_code } })).data,
      onSuccess: () => { invalidate(); toast.success("Paused"); },
    }),
  };
}
