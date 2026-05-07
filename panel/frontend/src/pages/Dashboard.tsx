import { Link } from "react-router-dom";
import { Activity, Boxes, PhoneCall, TrendingUp } from "lucide-react";
import { useDeployments } from "@/api/hooks/useDeployments";
import { useOverview, useTimeseries } from "@/api/hooks/useAnalytics";
import { useSystemHealth } from "@/api/hooks/useSystem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/StatusPill";
import { fmtDuration, fmtNumber, fmtPercent } from "@/lib/format";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function Dashboard() {
  const overview = useOverview();
  const ts = useTimeseries({ bucket: "day" });
  const deployments = useDeployments();
  const health = useSystemHealth();

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Tile
          label="Calls (last 7d)"
          value={overview.data ? fmtNumber(overview.data.total_calls) : null}
          icon={PhoneCall}
        />
        <Tile
          label="Avg handle time"
          value={overview.data ? fmtDuration(overview.data.avg_duration_sec) : null}
          icon={Activity}
        />
        <Tile
          label="Transfer rate"
          value={overview.data ? fmtPercent(overview.data.transfer_rate) : null}
          icon={TrendingUp}
        />
        <Tile
          label="Active deployments"
          value={
            deployments.data
              ? fmtNumber(deployments.data.items.filter((d) => d.status === "running").length)
              : null
          }
          icon={Boxes}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Calls per day</CardTitle></CardHeader>
          <CardContent className="h-[280px]">
            {ts.isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : ts.data && ts.data.points.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={ts.data.points.map((p) => ({
                    ...p, day: p.ts.slice(0, 10),
                  }))}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="day" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} />
                  <Tooltip />
                  <Line type="monotone" dataKey="calls" stroke="#4f46e5" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="transfers" stroke="#10b981" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full grid place-items-center text-sm text-slate-400">
                No call data yet — try connecting a deployment.
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>System health</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {health.isLoading ? (
              <Skeleton className="h-6 w-full" />
            ) : health.data ? (
              health.data.services.map((s) => (
                <div key={s.name} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700 capitalize">{s.name}</span>
                  <StatusPill status={s.status} />
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-400">Health check failed.</p>
            )}
            <Link
              to="/system/health"
              className="block text-xs text-indigo-600 hover:underline pt-2"
            >
              See details →
            </Link>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Deployments</CardTitle></CardHeader>
        <CardContent>
          {deployments.isLoading ? (
            <Skeleton className="h-12 w-full" />
          ) : deployments.data?.items.length === 0 ? (
            <p className="text-sm text-slate-500">
              No deployments yet. <Link to="/deployments" className="text-indigo-600 hover:underline">
                Create one →
              </Link>
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {deployments.data?.items.slice(0, 6).map((d) => (
                <Link
                  key={d.id}
                  to={`/deployments/${d.id}`}
                  className="block rounded-md border border-slate-200 p-3 hover:bg-slate-50"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm text-slate-900 truncate">
                      {d.vici_user}
                    </span>
                    <StatusPill status={d.status} />
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    Campaign {d.campaign_id}
                  </p>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Tile({
  label, value, icon: Icon,
}: {
  label: string;
  value: string | null;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <p className="mt-2 text-2xl font-semibold text-slate-900">
        {value ?? <Skeleton className="h-7 w-20" />}
      </p>
    </Card>
  );
}
