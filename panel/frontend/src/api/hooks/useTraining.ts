import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";

/**
 * Audio recordings the operator uploads to train the agent.
 * On the real backend each upload kicks off a transcription job; the
 * resulting `{user, agent}` pairs feed into the agent's few-shot pool
 * so the LLM sees examples of how a real human handled the call.
 */
export interface TrainingRecording {
  id: string;
  agent_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  label: string;
  status: "queued" | "transcribing" | "ready" | "error";
  transcript: string | null;
  uploaded_at: string;
  uploaded_by?: string | null;
}

export function useTrainingRecordings(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agents", agentId, "training-recordings"],
    queryFn: async () =>
      (await api.get<TrainingRecording[]>(
        `/agents/${agentId}/training-recordings`,
      )).data,
    enabled: !!agentId,
    refetchInterval: (q) => {
      // Poll while anything is still transcribing.
      const data = q.state.data as TrainingRecording[] | undefined;
      return data?.some((r) => r.status !== "ready" && r.status !== "error")
        ? 3000
        : false;
    },
  });
}

export function useUploadTrainingRecording(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { file: File; label?: string }) => {
      const fd = new FormData();
      fd.append("file", vars.file);
      if (vars.label) fd.append("label", vars.label);
      const r = await api.post<TrainingRecording>(
        `/agents/${agentId}/training-recordings`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-recordings"] });
      toast.success("Recording uploaded — transcribing now");
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail || "Upload failed";
      toast.error(msg);
    },
  });
}

export function useDeleteTrainingRecording(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (recordingId: string) => {
      await api.delete(`/agents/${agentId}/training-recordings/${recordingId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-recordings"] });
      toast.success("Removed");
    },
  });
}
