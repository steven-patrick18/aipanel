import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";
import type { KbDocument, KnowledgeBase, Page } from "@/lib/types";

export function useKbList() {
  return useQuery({
    queryKey: ["kb"],
    queryFn: async () => (await api.get<Page<KnowledgeBase>>("/kb")).data,
  });
}

export function useKb(kbId: string | undefined) {
  return useQuery({
    queryKey: ["kb", kbId],
    queryFn: async () =>
      (await api.get<KnowledgeBase>(`/kb/${kbId}`)).data,
    enabled: !!kbId,
  });
}

export function useKbDocuments(kbId: string | undefined) {
  return useQuery({
    queryKey: ["kb", kbId, "documents"],
    queryFn: async () =>
      (await api.get<KbDocument[]>(`/kb/${kbId}/documents`)).data,
    enabled: !!kbId,
  });
}

export function useCreateKb() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; description?: string; embedding_model?: string }) => {
      const r = await api.post<KnowledgeBase>("/kb", body);
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb"] });
      toast.success("Knowledge base created");
    },
  });
}

export function useUploadKbDocument(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post<KbDocument>(`/kb/${kbId}/documents`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb", kbId, "documents"] });
      toast.success("Document queued for ingest");
    },
  });
}

export function useSearchKb(kbId: string) {
  return useMutation({
    mutationFn: async (input: { query: string; limit?: number }) => {
      const r = await api.post(`/kb/${kbId}/search`, input);
      return r.data;
    },
  });
}
