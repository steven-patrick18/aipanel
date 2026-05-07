import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  useAgentRollup, useOverview, useTimeseries,
} from "@/api/hooks/useAnalytics";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { fmtDuration, fmtNumber, fmtPercent } from "@/lib/format";

const COLORS = ["#4f46e5", "#10b981", "#f59e0b", "#f43f5e", "#06b6d4", "#8b5cf6"];

export function Analytics() {
  const overview = useOverview();
  const timeseries = useTimeseries({ bucket: "day" });
  const agents = useAgentRollup();

  const dispoData = overview.data
    ? Object.entries(overview.data.dispo_breakdown).map(([k, v]) => ({ name: k, value: v }))
    : [];

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Last 7-day rollup. Materialised view refresh runs hourly."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <KpiTile label="Total calls" value={overview.data ? fmtNumber(overview.data.total_calls) : null} />
        <KpiTile label="Avg duration" value={overview.data ? fmtDuration(overview.data.avg_duration_sec) : null} />
        <KpiTile label="Transfer rate" value={overview.data ? fmtPercent(overview.data.transfer_rate) : null} />
        <KpiTile label="Dispo types" value={overview.data ? fmtNumber(Object.keys(overview.data.dispo_breakdown).length) : null} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle>Volume + transfers</CardTitle></CardHeader>
          <CardContent className="h-[300px]">
            {timeseries.isLoading ? <Skeleton className="h-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={(timeseries.data?.points ?? []).map(p => ({ ...p, day: p.ts.slice(0, 10) }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="day" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="calls" stroke="#4f46e5" strokeWidth={2} />
                  <Line type="monotone" dataKey="transfers" stroke="#10b981" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Outcomes breakdown</CardTitle></CardHeader>
          <CardContent className="h-[300px]">
            {overview.isLoading ? <Skeleton className="h-full" /> : dispoData.length === 0 ? (
              <p className="text-center text-sm text-slate-400 mt-20">No data yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={dispoData} dataKey="value" nameKey="name" outerRadius={90}>
                    {dispoData.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Per-agent volume</CardTitle></CardHeader>
          <CardContent className="h-[280px]">
            {agents.isLoading ? <Skeleton className="h-full" /> : (agents.data?.rows ?? []).length === 0 ? (
              <p className="text-center text-sm text-slate-400 mt-20">No agent activity yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={agents.data!.rows}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="agent_name" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} />
                  <Tooltip />
                  <Bar dataKey="total_calls" fill="#4f46e5" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function KpiTile({ label, value }: { label: string; value: string | null }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900">
        {value ?? <Skeleton className="h-7 w-20" />}
      </p>
    </Card>
  );
}
