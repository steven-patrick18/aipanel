import { Server } from "lucide-react";
import { useNodes } from "@/api/hooks/useSystem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtRelative } from "@/lib/format";

export function Cluster() {
  const { data, isLoading } = useNodes();

  return (
    <>
      <PageHeader
        title="Cluster"
        description="Nodes auto-register themselves on heartbeat. Add a second node by running install.sh on it with --join."
      />

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          icon={Server}
          title="No nodes registered"
          description="The current node will register itself when aipanel-web heartbeats."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data!.map((n) => (
            <Card key={n.id}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between text-sm">
                  {n.hostname}
                  <StatusPill status={n.status} />
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-1.5">
                <p className="text-slate-500">Role: <span className="text-slate-700">{n.role}</span></p>
                <p className="text-slate-500">
                  Services: <span className="text-slate-700">{n.services.join(", ") || "—"}</span>
                </p>
                <p className="text-slate-500">
                  Last heartbeat: <span className="text-slate-700">{fmtRelative(n.last_heartbeat_at)}</span>
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
