import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Download, Loader2, RefreshCw,
  Rewind, Upload as UploadIcon,
} from "lucide-react";
import {
  useApplyUpdate, useUpdateInfo, useUpdateRun,
} from "@/api/hooks/useUpdates";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/PageHeader";

/**
 * System → Updates — wraps update.sh in a button.
 *
 * Picks up commits + tags from the installed git repo, lets the admin
 * roll forward to a tag (or back to the previous one), and tails the
 * update.sh log live.
 *
 * The actual update logic — DB backup, dependency-aware restarts,
 * auto-rollback on failure — all stays in update.sh. This page just
 * triggers it and shows the output.
 */
export function Updates() {
  const info = useUpdateInfo();
  const apply = useApplyUpdate();
  const [selectedTag, setSelectedTag] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const start = async (vars: {
    target?: string; rollback?: boolean; skip_backup?: boolean;
  }) => {
    const id = await apply.mutateAsync(vars);
    setActiveRunId(id);
  };

  return (
    <>
      <PageHeader
        title="Updates"
        description="Roll forward to the latest release or roll back to the previous one. Backed by update.sh — DB backup + auto-rollback on failure."
        actions={
          <Button
            type="button" variant="outline"
            onClick={() => info.refetch()}
            disabled={info.isFetching}
          >
            <RefreshCw className={`h-4 w-4 ${info.isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ------------- Current state ------------- */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Currently installed</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {info.isLoading || !info.data ? (
              <Skeleton className="h-12 w-full" />
            ) : (
              <>
                <Row label="Version" value={info.data.current_version} mono />
                <Row label="Commit" value={info.data.current_sha.slice(0, 12)} mono />
                <Row
                  label="Latest available"
                  value={info.data.latest_tag ?? "—"}
                  mono
                />
                <Row
                  label="Commits behind"
                  value={
                    info.data.behind_count > 0 ? (
                      <span className="text-amber-700 font-medium">
                        {info.data.behind_count} behind
                      </span>
                    ) : (
                      <span className="text-emerald-700">up to date</span>
                    )
                  }
                />
              </>
            )}
          </CardContent>
        </Card>

        {/* ------------- Apply ------------- */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Apply an update</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-xs uppercase tracking-wide text-slate-500">
                Target version
              </label>
              <Select
                value={selectedTag}
                onValueChange={setSelectedTag}
                disabled={!info.data?.available_tags?.length}
              >
                <SelectTrigger>
                  <SelectValue placeholder={
                    info.data?.latest_tag
                      ? `Latest (${info.data.latest_tag})`
                      : "No tags available"
                  } />
                </SelectTrigger>
                <SelectContent>
                  {(info.data?.available_tags ?? []).map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[11px] text-slate-500">
                Leave blank to update to the latest tag.
              </p>
            </div>

            <div className="flex items-center gap-2 pt-2">
              <Button
                type="button"
                disabled={
                  apply.isPending ||
                  info.data?.update_in_progress ||
                  !!activeRunId
                }
                onClick={() => {
                  if (!confirm(
                    "Apply update now? The system will back up Postgres + " +
                    "config, fetch code, restart services, and roll back " +
                    "automatically if anything fails."
                  )) return;
                  start({ target: selectedTag || undefined });
                }}
              >
                {apply.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Starting…</>
                ) : (
                  <><UploadIcon className="h-4 w-4" /> Apply update</>
                )}
              </Button>

              {info.data?.has_previous && (
                <Button
                  type="button" variant="outline"
                  disabled={apply.isPending || !!activeRunId}
                  onClick={() => {
                    if (!confirm(
                      "Roll back to the previously-installed version? " +
                      "The DB will be restored from the last pre-update backup."
                    )) return;
                    start({ rollback: true });
                  }}
                >
                  <Rewind className="h-4 w-4" /> Rollback
                </Button>
              )}
            </div>

            {info.data?.update_in_progress && !activeRunId && (
              <p className="text-xs text-amber-700 flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" />
                Another update is already in progress.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ------------- Live log ------------- */}
      {activeRunId && (
        <UpdateRunLog runId={activeRunId} onClose={() => {
          setActiveRunId(null);
          info.refetch();
        }} />
      )}
    </>
  );
}

function Row({
  label, value, mono,
}: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <span className={mono ? "font-mono text-xs text-slate-700" : "text-slate-700"}>
        {value}
      </span>
    </div>
  );
}

function UpdateRunLog({ runId, onClose }: { runId: string; onClose: () => void }) {
  const run = useUpdateRun(runId);
  const ref = useRef<HTMLPreElement>(null);

  // Auto-scroll to bottom as lines arrive.
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [run.data?.lines?.length]);

  const status = run.data?.status;
  const Icon = status === "ok" ? CheckCircle2
             : status === "running" ? Loader2 : AlertTriangle;
  const tone = status === "ok" ? "text-emerald-600"
             : status === "running" ? "text-indigo-500" : "text-red-600";

  return (
    <Card className="mt-6 p-0 overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base flex items-center gap-2">
          <Icon className={`h-4 w-4 ${tone} ${status === "running" ? "animate-spin" : ""}`} />
          Update log — <span className="text-slate-500 font-normal">{status}</span>
        </CardTitle>
        {status !== "running" && (
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
        )}
      </CardHeader>
      <CardContent>
        <pre
          ref={ref}
          className="max-h-[420px] min-h-[160px] overflow-y-auto rounded-md
                     bg-slate-900 text-slate-100 text-xs font-mono p-3
                     leading-relaxed"
        >
          {(run.data?.lines ?? []).join("\n") || "Connecting…"}
        </pre>
        {status === "ok" && (
          <div className="mt-3 text-sm text-emerald-700 flex items-center gap-1.5">
            <CheckCircle2 className="h-4 w-4" /> Update completed.
            <Button variant="link" size="sm" className="px-1 h-auto"
                    onClick={() => location.reload()}>
              <Download className="h-3 w-3" /> Reload UI
            </Button>
          </div>
        )}
        {(status === "failed" || status === "error") && (
          <p className="mt-3 text-sm text-red-700 flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4" />
            Update failed (exit {run.data?.exit_code}).
            update.sh auto-rolled back the system to the previous version.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
