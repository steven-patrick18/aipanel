import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { Page, VicidialServer } from "@/lib/types";

export function useVicidialServers() {
  return useQuery({
    queryKey: ["vicidial-servers"],
    queryFn: async () =>
      (await api.get<Page<VicidialServer>>("/vicidial-servers")).data,
  });
}

export function useCreateVicidialServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: any) => {
      const r = await api.post<VicidialServer>("/vicidial-servers", body);
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vicidial-servers"] });
      toast.success("ViciDial server registered");
    },
  });
}

export function useTestVicidialConnection(id: string) {
  return useMutation({
    mutationFn: async () => {
      const r = await api.post(`/vicidial-servers/${id}/test-connection`);
      return r.data;
    },
  });
}

export interface ViciCampaign { code: string; name: string; }
export interface ViciIngroup { code: string; name: string; }

/**
 * Read available campaigns from a registered ViciDial server.
 * The "New deployment" form uses this to fill the campaign dropdown.
 */
export function useViciCampaigns(serverId: string | undefined) {
  return useQuery({
    queryKey: ["vicidial-servers", serverId, "campaigns"],
    queryFn: async () =>
      (await api.get<ViciCampaign[]>(
        `/vicidial-servers/${serverId}/campaigns`,
      )).data,
    enabled: !!serverId,
  });
}

/**
 * Read available inbound groups (transfer targets) from a ViciDial server.
 * Used to populate the "Allowed transfer ingroups" multi-select.
 */
export function useViciIngroups(serverId: string | undefined) {
  return useQuery({
    queryKey: ["vicidial-servers", serverId, "ingroups"],
    queryFn: async () =>
      (await api.get<ViciIngroup[]>(
        `/vicidial-servers/${serverId}/ingroups`,
      )).data,
    enabled: !!serverId,
  });
}
