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
