import { useParams } from "react-router-dom";
import { Pause, Phone, Play, Square } from "lucide-react";
import { useDeployment, useDeploymentControl } from "@/api/hooks/useDeployments";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { LiveTranscript } from "@/components/LiveTranscript";
import { AudioWaveform } from "@/components/AudioWaveform";
import { canWrite } from "@/lib/permissions";
import { useAuth } from "@/auth/store";
import { fmtRelative } from "@/lib/format";

export function DeploymentDetail() {
  const { id } = useParams<{ id: string }>();
  const role = useAuth((s) => s.user?.role);
  const { data: dep, isLoading } = useDeployment(id);
  const ctl = useDeploymentControl(id!);

  if (isLoading || !dep) return <LoadingSpinner />;

  const isRunning = dep.status === "running";
  const writeable = canWrite(role);

  return (
    <>
      <PageHeader
        title={`Deployment ${dep.vici_user}`}
        description={`Campaign ${dep.campaign_id} · phone ${dep.phone_login}`}
        actions={
          <div className="flex items-center gap-2">
            <StatusPill status={dep.status} />
            {writeable && (
              <>
                <Button
                  size="sm" variant="success"
                  onClick={() => ctl.start.mutate()}
                  disabled={isRunning || ctl.start.isPending}
                >
                  <Play className="h-4 w-4" /> Start
                </Button>
                <Button
                  size="sm" variant="secondary"
                  onClick={() => ctl.pause.mutate("BREAK")}
                  disabled={!isRunning || ctl.pause.isPending}
                >
                  <Pause className="h-4 w-4" /> Pause
                </Button>
                <Button
                  size="sm" variant="destructive"
                  onClick={() => {
                    if (confirm("Stop deployment and log out the ViciDial session?")) {
                      ctl.stop.mutate();
                    }
                  }}
                  disabled={ctl.stop.isPending}
                >
                  <Square className="h-4 w-4" /> Stop
                </Button>
              </>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Phone className={isRunning ? "h-4 w-4 text-emerald-500" : "h-4 w-4 text-slate-400"} />
                Inbound audio
              </CardTitle>
            </CardHeader>
            <CardContent>
              <AudioWaveform active={isRunning} />
            </CardContent>
          </Card>

          <LiveTranscript deploymentId={id!} />
        </div>

        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent>
            <dl className="text-sm space-y-2">
              <DLRow label="Status" value={<StatusPill status={dep.status} />} />
              <DLRow label="Last heartbeat" value={fmtRelative(dep.last_heartbeat_at)} />
              <DLRow label="Created" value={fmtRelative(dep.created_at)} />
              <DLRow label="Allowed transfers" value={
                dep.allowed_transfer_ingroups.length
                  ? dep.allowed_transfer_ingroups.join(", ")
                  : <span className="text-slate-400">none</span>
              } />
            </dl>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function DLRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-slate-700 text-right">{value}</dd>
    </div>
  );
}
