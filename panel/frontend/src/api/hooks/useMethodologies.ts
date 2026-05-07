import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import type { MethodologyDetail, MethodologySummary } from "@/lib/types";

export function useMethodologies() {
  return useQuery({
    queryKey: ["methodologies"],
    queryFn: async () =>
      (await api.get<MethodologySummary[]>("/methodologies")).data,
    staleTime: 5 * 60_000,    // catalog rarely changes
  });
}

export function useMethodology(key: string | undefined) {
  return useQuery({
    queryKey: ["methodologies", key],
    queryFn: async () =>
      (await api.get<MethodologyDetail>(`/methodologies/${key}`)).data,
    enabled: !!key,
    staleTime: 5 * 60_000,
  });
}
