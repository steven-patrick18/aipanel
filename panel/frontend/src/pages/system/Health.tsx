import { useSystemHealth, useSystemVersion } from "@/api/hooks/useSystem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtRelative } from "@/lib/format";

export function Health() {
  const health = useSystemHealth();
  const version = useSystemVersion();

  return (
    <>
      <PageHeader
        title="Health"
        description={
          version.data
            ? `aipanel ${version.data.version} · last checked ${
                health.data ? fmtRelative(health.data.checked_at) : "—"
              }`
            : "Live status of every aipanel service."
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            Services
            {health.data && <StatusPill status={health.data.overall} />}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {health.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : !health.data ? (
            <p className="text-sm text-rose-600">Could not reach health endpoint.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {health.data.services.map((s) => (
                <li key={s.name} className="flex items-center justify-between py-2.5 text-sm">
                  <div>
                    <p className="font-medium capitalize text-slate-900">{s.name}</p>
                    <p className="text-xs text-slate-500">{s.detail || "—"}</p>
                  </div>
                  <StatusPill status={s.status} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}
