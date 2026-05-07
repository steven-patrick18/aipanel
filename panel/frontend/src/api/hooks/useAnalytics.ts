import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import type {
  AgentRollup,
  OverviewResponse,
  TimeseriesResponse,
} from "@/lib/types";

interface PeriodParams {
  period_start?: string;
  period_end?: string;
}

export function useOverview(params: PeriodParams = {}) {
  return useQuery({
    queryKey: ["analytics", "overview", params],
    queryFn: async () =>
      (await api.get<OverviewResponse>("/analytics/overview", { params })).data,
  });
}

export function useAgentRollup(params: PeriodParams = {}) {
  return useQuery({
    queryKey: ["analytics", "agents", params],
    queryFn: async () =>
      (await api.get<{ rows: AgentRollup[] }>("/analytics/agents", { params })).data,
  });
}

export function useTimeseries(
  params: PeriodParams & { bucket?: "hour" | "day" } = {},
) {
  return useQuery({
    queryKey: ["analytics", "timeseries", params],
    queryFn: async () =>
      (await api.get<TimeseriesResponse>("/analytics/timeseries", { params })).data,
  });
}
