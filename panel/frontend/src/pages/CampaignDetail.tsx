import { useState } from "react";
import { useParams } from "react-router-dom";
import { Bot, RefreshCw, Sparkles, Target, User } from "lucide-react";
import {
  useCampaign,
  useCampaignFewShot,
  useCampaignMetrics,
  useRefreshFewShot,
  useUpdateCampaign,
} from "@/api/hooks/useCampaigns";
import { useMethodology } from "@/api/hooks/useMethodologies";
import { useAuth } from "@/auth/store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { MethodologyPicker } from "@/components/MethodologyPicker";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtDuration, fmtNumber, fmtPercent, fmtRelative } from "@/lib/format";
import { canWrite } from "@/lib/permissions";
import type { CampaignMethodology } from "@/lib/types";

export function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const role = useAuth((s) => s.user?.role);
  const { data: c, isLoading } = useCampaign(id);
  const { data: metrics } = useCampaignMetrics(id, 30);
  const { data: pool } = useCampaignFewShot(id);
  const update = useUpdateCampaign(id!);
  const refresh = useRefreshFewShot(id!);
  const [pickerOpen, setPickerOpen] = useState(false);
  const { data: methodologyDetail } = useMethodology(c?.methodology);

  if (isLoading || !c) return <LoadingSpinner />;

  const writeable = canWrite(role);

  return (
    <>
      <PageHeader
        title={c.name}
        description={c.objective || "No objective set yet."}
        actions={
          <div className="flex items-center gap-2">
            <StatusPill status={c.status} />
            {writeable && (
              <Select
                value={c.status}
                onValueChange={(v) => update.mutate({ status: v })}
              >
                <SelectTrigger className="h-9 w-[140px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="draft">draft</SelectItem>
                  <SelectItem value="active">active</SelectItem>
                  <SelectItem value="paused">paused</SelectItem>
                  <SelectItem value="archived">archived</SelectItem>
                </SelectContent>
              </Select>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2">
                <Target className="h-4 w-4 text-indigo-500" />
                Methodology
              </span>
              {writeable && (
                <Button size="sm" variant="ghost"
                        onClick={() => setPickerOpen(true)}>
                  Change
                </Button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-base font-medium text-slate-900">
              {methodologyDetail?.name ?? c.methodology}
            </p>
            <p className="text-sm text-slate-500 mt-1">
              {methodologyDetail?.tagline ?? ""}
            </p>
            {methodologyDetail?.stages && methodologyDetail.stages.length > 0 && (
              <div className="mt-3 pt-3 border-t border-slate-100">
                <p className="text-[11px] uppercase tracking-wide text-slate-400 mb-1.5">
                  Call stages
                </p>
                <ol className="space-y-0.5 text-xs text-slate-600">
                  {methodologyDetail.stages.map((s, i) => (
                    <li key={i}>
                      <span className="font-medium text-slate-700">{i + 1}.</span> {s.name}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </CardContent>
        </Card>

        <MethodologyPicker
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          current={c.methodology as CampaignMethodology}
          onSelect={(key) => update.mutate({ methodology: key })}
        />

        <Card>
          <CardHeader><CardTitle>Success criteria</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm text-slate-600 mb-2">
              Calls with these disposition codes count as "won":
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(c.success_dispos ?? []).map((d) => (
                <Badge key={d} variant="success">{d}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Conversion (last 30d)</CardTitle></CardHeader>
          <CardContent>
            {!metrics ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <p className="text-3xl font-semibold text-slate-900">
                  {fmtPercent(metrics.conversion_rate)}
                </p>
                <p className="text-sm text-slate-500 mt-1">
                  {fmtNumber(metrics.successful_calls)} of {fmtNumber(metrics.total_calls)} calls
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  Avg AHT {fmtDuration(metrics.avg_duration_sec)}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-amber-500" />
                Few-shot pool ({(pool ?? []).length})
              </span>
              {writeable && (
                <Button
                  size="sm" variant="secondary"
                  onClick={() => refresh.mutate()}
                  disabled={refresh.isPending}
                >
                  <RefreshCw className="h-4 w-4" /> Re-mine now
                </Button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!pool ? (
              <Skeleton className="h-24 w-full" />
            ) : pool.length === 0 ? (
              <p className="text-sm text-slate-400">
                Nothing mined yet. Run at least a handful of successful calls
                with this campaign assigned, then click "Re-mine now" — the
                top exchanges will land here and get injected into the LLM
                prompt automatically.
              </p>
            ) : (
              <div className="space-y-4">
                {pool.map((ex, i) => (
                  <div key={i} className="rounded-md border border-slate-200 p-3 bg-slate-50/40">
                    <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
                      <span>Example {i + 1}</span>
                      <span>score {ex.score.toFixed(2)} · mined {fmtRelative(ex.mined_at)}</span>
                    </div>
                    <div className="space-y-2">
                      <div className="flex gap-2 items-start">
                        <span className="h-6 w-6 rounded-full bg-slate-200 grid place-items-center shrink-0">
                          <User className="h-3 w-3 text-slate-600" />
                        </span>
                        <p className="text-sm text-slate-900">{ex.user}</p>
                      </div>
                      <div className="flex gap-2 items-start">
                        <span className="h-6 w-6 rounded-full bg-indigo-100 grid place-items-center shrink-0">
                          <Bot className="h-3 w-3 text-indigo-700" />
                        </span>
                        <p className="text-sm text-indigo-900">{ex.agent}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
