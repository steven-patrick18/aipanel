import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";

export interface TrainingExample {
  id: string;
  kind: "manual" | "call";
  user: string;
  agent: string;
  notes?: string;
  call_id?: string | null;
  recording_path?: string | null;
  added_at: string;
  added_by?: string | null;
}

export function useTrainingExamples(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agents", agentId, "training-examples"],
    queryFn: async () =>
      (await api.get<TrainingExample[]>(`/agents/${agentId}/training-examples`))
        .data,
    enabled: !!agentId,
  });
}

export function useAddTrainingExample(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { user: string; agent: string; notes?: string }) =>
      (await api.post<TrainingExample>(
        `/agents/${agentId}/training-examples`, body,
      )).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-examples"] });
      toast.success("Training example added");
    },
  });
}

export function useDeleteTrainingExample(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (exampleId: string) => {
      await api.delete(`/agents/${agentId}/training-examples/${exampleId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", agentId, "training-examples"] });
      toast.success("Removed");
    },
  });
}

export function useMarkExemplar(callId: string) {
  return useMutation({
    mutationFn: async (vars: {
      agent_id?: string;
      user_turn: string;
      agent_turn: string;
      notes?: string;
    }) => {
      await api.post(`/calls/${callId}/mark-exemplar`, vars);
    },
    onSuccess: () => {
      toast.success("Saved as a training example for this agent");
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail || "Failed to mark exemplar";
      toast.error(msg);
    },
  });
}
