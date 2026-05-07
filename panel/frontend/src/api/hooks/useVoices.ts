import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { Page, Voice } from "@/lib/types";

export function useVoices() {
  return useQuery({
    queryKey: ["voices"],
    queryFn: async () => (await api.get<Page<Voice>>("/voices")).data,
  });
}

export function useVoice(id: string | undefined) {
  return useQuery({
    queryKey: ["voices", id],
    queryFn: async () => (await api.get<Voice>(`/voices/${id}`)).data,
    enabled: !!id,
  });
}

export function useCloneVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string; ref_text: string; audio: File }) => {
      const fd = new FormData();
      fd.append("name", input.name);
      fd.append("ref_text", input.ref_text);
      fd.append("audio", input.audio);
      const r = await api.post<Voice>("/voices", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["voices"] });
      toast.success("Voice queued for cloning");
    },
  });
}

export function useDeleteVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/voices/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["voices"] });
      toast.success("Voice deleted");
    },
  });
}
