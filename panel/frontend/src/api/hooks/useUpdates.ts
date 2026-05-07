import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../client";

export interface UpdateInfo {
  current_version: string;
  current_sha: string;
  latest_tag: string | null;
  behind_count: number;
  available_tags: string[];
  has_previous: boolean;
  update_in_progress: boolean;
}

export function useUpdateInfo() {
  return useQuery({
    queryKey: ["system", "updates", "info"],
    queryFn: async () =>
      (await api.get<UpdateInfo>("/system/updates/info")).data,
    refetchInterval: 30_000,
  });
}

export interface UpdateRun {
  id: string;
  status: "running" | "ok" | "failed" | "error";
  exit_code: number | null;
  started_at: string;
  lines: string[];
}

export function useUpdateRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["system", "updates", "runs", runId],
    queryFn: async () =>
      (await api.get<UpdateRun>(`/system/updates/runs/${runId}`)).data,
    enabled: !!runId,
    refetchInterval: (q) => {
      const data = q.state.data as UpdateRun | undefined;
      return data?.status === "running" ? 1000 : false;
    },
  });
}

export function useApplyUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      target?: string;
      rollback?: boolean;
      skip_backup?: boolean;
    }) => {
      const r = await api.post<{ run_id: string }>(
        "/system/updates/apply", vars,
      );
      return r.data.run_id;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "updates", "info"] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Could not start update");
    },
  });
}
