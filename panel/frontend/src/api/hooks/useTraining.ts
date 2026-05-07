import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";

// ---------------------------------------------------------------------------
// Capability score — how trained is this agent?
// ---------------------------------------------------------------------------

export interface CapabilityBreakdown {
  key: string;
  label: string;
  points: number;
  max: number;
  done: boolean;
}

export interface AgentCapability {
  score: number;
  breakdown: CapabilityBreakdown[];
}

export function useAgentCapability(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agents", agentId, "capability"],
    queryFn: async () =>
      (await api.get<AgentCapability>(`/agents/${agentId}/capability`)).data,
    enabled: !!agentId,
    refetchInterval: 5000,
  });
}

// ---------------------------------------------------------------------------
// Training script — single text blob the operator pastes in.
// ---------------------------------------------------------------------------

export function useTrainingScript(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agents", agentId, "training-script"],
    queryFn: async () =>
      (await api.get<{ script: string }>(`/agents/${agentId}/training-script`)).data,
    enabled: !!agentId,
  });
}

export function useSaveTrainingScript(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (script: string) =>
      (await api.put<{ script: string }>(
        `/agents/${agentId}/training-script`, { script },
      )).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-script"] });
      qc.invalidateQueries({ queryKey: ["agents", agentId, "capability"] });
      toast.success("Script saved");
    },
  });
}

// ---------------------------------------------------------------------------
// Training recordings — operator-uploaded audio.
// ---------------------------------------------------------------------------

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
      const data = q.state.data as TrainingRecording[] | undefined;
      return data?.some((r) => r.status !== "ready" && r.status !== "error")
        ? 3000 : false;
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
        `/agents/${agentId}/training-recordings`, fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-recordings"] });
      qc.invalidateQueries({ queryKey: ["agents", agentId, "capability"] });
      toast.success("Recording uploaded");
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Upload failed");
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
      qc.invalidateQueries({ queryKey: ["agents", agentId, "capability"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Chat sandbox — talk to the agent + save good answers as training.
// ---------------------------------------------------------------------------

export function useAgentChat(agentId: string) {
  return useMutation({
    mutationFn: async (message: string) => {
      const r = await api.post<{ reply: string }>(
        `/agents/${agentId}/chat`, { message },
      );
      return r.data.reply;
    },
  });
}

export interface TrainingChat {
  id: string;
  user: string;
  agent: string;
  saved_at: string;
}

export function useTrainingChats(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agents", agentId, "training-chats"],
    queryFn: async () =>
      (await api.get<TrainingChat[]>(`/agents/${agentId}/training-chats`)).data,
    enabled: !!agentId,
  });
}

export function useSaveTrainingChat(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { user: string; agent: string }) => {
      const r = await api.post<TrainingChat>(
        `/agents/${agentId}/training-chats`, vars,
      );
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-chats"] });
      qc.invalidateQueries({ queryKey: ["agents", agentId, "capability"] });
      toast.success("Saved as training");
    },
  });
}

export function useDeleteTrainingChat(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (chatId: string) => {
      await api.delete(`/agents/${agentId}/training-chats/${chatId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-chats"] });
      qc.invalidateQueries({ queryKey: ["agents", agentId, "capability"] });
    },
  });
}
