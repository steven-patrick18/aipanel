import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type {
  Campaign,
  CampaignDetail,
  CampaignMetrics,
  FewShotExample,
  Page,
} from "@/lib/types";

export function useCampaigns(status?: string) {
  return useQuery({
    queryKey: ["campaigns", status],
    queryFn: async () =>
      (await api.get<Page<Campaign>>("/campaigns", { params: { status } })).data,
  });
}

export function useCampaign(id: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", id],
    queryFn: async () => (await api.get<CampaignDetail>(`/campaigns/${id}`)).data,
    enabled: !!id,
  });
}

export function useCampaignMetrics(id: string | undefined, periodDays = 30) {
  return useQuery({
    queryKey: ["campaigns", id, "metrics", periodDays],
    queryFn: async () => (
      await api.get<CampaignMetrics>(`/campaigns/${id}/metrics`,
        { params: { period_days: periodDays } })
    ).data,
    enabled: !!id,
  });
}

export function useCampaignFewShot(id: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", id, "few-shot"],
    queryFn: async () => (
      await api.get<FewShotExample[]>(`/campaigns/${id}/few-shot-pool`)
    ).data,
    enabled: !!id,
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: any) => {
      const r = await api.post<CampaignDetail>("/campaigns", body);
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign created");
    },
  });
}

export function useUpdateCampaign(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: any) => {
      const r = await api.patch<CampaignDetail>(`/campaigns/${id}`, body);
      return r.data;
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.setQueryData(["campaigns", id], data);
      toast.success("Saved");
    },
  });
}

export function useArchiveCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/campaigns/${id}`);
      return id;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign archived");
    },
  });
}

export function useRefreshFewShot(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post(`/campaigns/${id}/refresh-few-shot`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns", id] });
      toast.success("Mining job queued — refresh in ~30s");
    },
  });
}
