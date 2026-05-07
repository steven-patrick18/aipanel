import { Badge } from "@/components/ui/badge";

const VARIANT_FOR: Record<string, "primary" | "success" | "warning" | "danger" | "muted" | "default"> = {
  // Deployments
  running:  "success",
  starting: "warning",
  stopped:  "muted",
  error:    "danger",
  // Agents
  draft:    "warning",
  ready:    "success",
  archived: "muted",
  // Voices / KB docs
  pending:    "warning",
  processing: "primary",
  training:   "primary",
  // Calls
  completed: "success",
  abandoned: "muted",
  ok:        "success",
  degraded:  "warning",
  down:      "danger",
};

export function StatusPill({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge variant="muted">—</Badge>;
  const variant = VARIANT_FOR[status.toLowerCase()] ?? "default";
  return <Badge variant={variant} className="capitalize">{status}</Badge>;
}
