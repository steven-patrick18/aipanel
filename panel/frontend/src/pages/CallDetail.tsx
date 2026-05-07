import { useState } from "react";
import { useParams } from "react-router-dom";
import { Bot, Download, PhoneForwarded, User } from "lucide-react";
import {
  useCall,
  useCallEvents,
  useCallRecording,
  useCallTranscript,
  useTransferCall,
  useTransferOptions,
} from "@/api/hooks/useCalls";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PageHeader } from "@/components/PageHeader";
import { useAuth } from "@/auth/store";
import { canWrite } from "@/lib/permissions";
import { fmtDate, fmtDuration, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

export function CallDetail() {
  const { id } = useParams<{ id: string }>();
  const role = useAuth((s) => s.user?.role);
  const call = useCall(id);
  const transcript = useCallTranscript(id);
  const events = useCallEvents(id);
  const recording = useCallRecording(id);

  if (call.isLoading || !call.data) return <LoadingSpinner />;

  const c = call.data;
  const isLive = c.ended_at === null || c.ended_at === undefined;

  return (
    <>
      <PageHeader
        title={`Call ${c.id.slice(0, 8)}`}
        description={`${fmtDate(c.started_at)} · ${
          isLive ? "in progress" : fmtDuration(c.duration_sec)
        } · outcome ${c.outcome ?? "—"}${
          c.transfer_target ? ` · transferred → ${c.transfer_target}` : ""
        }`}
        actions={
          <div className="flex items-center gap-2">
            {isLive && canWrite(role) && id && (
              <TransferButton callId={id} />
            )}
            {recording.data && (
              <Button asChild>
                <a href={recording.data.url} target="_blank" rel="noopener noreferrer">
                  <Download className="h-4 w-4" /> Download recording
                </a>
              </Button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2 p-0">
          <CardHeader><CardTitle>Transcript</CardTitle></CardHeader>
          <CardContent>
            {transcript.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (transcript.data?.turns ?? []).length === 0 ? (
              <p className="text-sm text-slate-400">No transcript available.</p>
            ) : (
              <div className="space-y-3">
                {transcript.data!.turns.map((t, i) => (
                  <div
                    key={i}
                    className={cn("flex gap-2.5",
                      t.role === "agent" ? "" : "flex-row-reverse"
                    )}
                  >
                    <div
                      className={cn(
                        "h-7 w-7 rounded-full grid place-items-center shrink-0",
                        t.role === "agent"
                          ? "bg-indigo-100 text-indigo-700"
                          : "bg-slate-100 text-slate-600",
                      )}
                    >
                      {t.role === "agent"
                        ? <Bot className="h-3.5 w-3.5" />
                        : <User className="h-3.5 w-3.5" />}
                    </div>
                    <div className={cn("max-w-[78%]", t.role === "agent" ? "" : "text-right")}>
                      <div
                        className={cn("rounded-lg px-3 py-2 text-sm",
                          t.role === "agent"
                            ? "bg-indigo-50 text-indigo-900"
                            : "bg-slate-100 text-slate-900",
                        )}
                      >
                        {t.text}
                      </div>
                      <p className="mt-1 text-[11px] text-slate-400">{fmtDate(t.ts)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Events</CardTitle></CardHeader>
          <CardContent>
            {events.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (events.data ?? []).length === 0 ? (
              <p className="text-sm text-slate-400">No events recorded.</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {events.data!.map((e) => (
                  <li key={e.id} className="border-l-2 border-slate-200 pl-2">
                    <p className="font-medium text-slate-700">{e.event_type}</p>
                    <p className="text-slate-400">{fmtRelative(e.ts)}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function TransferButton({ callId }: { callId: string }) {
  const [open, setOpen] = useState(false);
  const [ingroup, setIngroup] = useState("");
  const [customIngroup, setCustomIngroup] = useState("");
  const [summary, setSummary] = useState("");
  const { data: options, isLoading } = useTransferOptions(callId, open);
  const transfer = useTransferCall(callId);

  const effectiveIngroup =
    ingroup === "__custom" ? customIngroup.trim() : ingroup.trim();

  const submit = async () => {
    if (!effectiveIngroup) return;
    if (!confirm(
      `Transfer this live call to ingroup "${effectiveIngroup}"? ` +
      `The AI agent will drop off and a human queue will pick up.`
    )) return;
    await transfer.mutateAsync({
      ingroup_id: effectiveIngroup,
      summary: summary.trim() || undefined,
    });
    setOpen(false);
    setIngroup("");
    setCustomIngroup("");
    setSummary("");
  };

  const hasOptions = (options ?? []).length > 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button
        type="button" variant="secondary"
        onClick={() => setOpen(true)}
      >
        <PhoneForwarded className="h-4 w-4" /> Transfer to ingroup
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Forward this call to a ViciDial ingroup</DialogTitle>
          <DialogDescription>
            ViciDial bridges the customer leg into the chosen queue and the AI
            agent drops off. Pick from the deployment's allow-list, or enter a
            custom ingroup ID if your campaign accepts it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tx-ingroup">Ingroup</Label>
            {isLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Select value={ingroup} onValueChange={setIngroup}>
                <SelectTrigger id="tx-ingroup">
                  <SelectValue placeholder={
                    hasOptions ? "Choose an ingroup…" : "No ingroups in allow-list"
                  } />
                </SelectTrigger>
                <SelectContent>
                  {(options ?? []).map((o) => (
                    <SelectItem key={o.id} value={o.id}>{o.label}</SelectItem>
                  ))}
                  <SelectItem value="__custom">Custom ingroup ID…</SelectItem>
                </SelectContent>
              </Select>
            )}
            {!isLoading && !hasOptions && (
              <p className="text-xs text-amber-600">
                This deployment has no allowed_transfer_ingroups configured —
                only a custom ID will work, and only if ViciDial accepts it
                from this agent seat.
              </p>
            )}
          </div>

          {ingroup === "__custom" && (
            <div className="space-y-1.5">
              <Label htmlFor="tx-custom">Custom ingroup ID</Label>
              <Input
                id="tx-custom"
                value={customIngroup}
                onChange={(e) => setCustomIngroup(e.target.value)}
                placeholder="e.g. SALES, BILLING_TIER2"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="tx-summary">Summary for the human agent (optional)</Label>
            <Textarea
              id="tx-summary" rows={3}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Caller wants to escalate billing dispute about Mar invoice…"
            />
            <p className="text-xs text-slate-500">
              Goes into the call notes ViciDial passes to the receiving agent.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type="button"
                  disabled={transfer.isPending || !effectiveIngroup}
                  onClick={submit}>
            {transfer.isPending ? "Transferring…" : "Transfer now"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


