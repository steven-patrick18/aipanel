import { useEffect, useState } from "react";
import {
  Check, Cpu, Headphones, Loader2, Network, Plus, Server,
  Trash2,
} from "lucide-react";
import {
  useCreateJoinToken,
  useDrainNode,
  useNodes,
  useRemoveNode,
  type JoinTokenCreated,
  type NodeRole,
} from "@/api/hooks/useSystem";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtRelative } from "@/lib/format";

export function Cluster() {
  const { data: nodes, isLoading } = useNodes();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Cluster"
        description="Nodes auto-register on heartbeat. Add a node to scale GPU, app, or SIP capacity horizontally."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> Add node</Button>
            </DialogTrigger>
            <AddNodeDialog onClose={() => setOpen(false)} />
          </Dialog>
        }
      />

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (nodes ?? []).length === 0 ? (
        <EmptyState
          icon={Server}
          title="No nodes registered"
          description="The current node will register itself on first heartbeat."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {nodes!.map((n) => <NodeCard key={n.id} node={n} />)}
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// One node card — drain / remove buttons live here
// ---------------------------------------------------------------------------

function NodeCard({ node }: { node: any }) {
  const drain = useDrainNode();
  const remove = useRemoveNode();

  const isPrimary = node.role === "primary";
  const drained = node.status === "drained" || node.status === "draining";
  const RoleIcon = roleIcon(node.role);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-2">
            <RoleIcon className="h-4 w-4 text-slate-500" />
            {node.hostname}
          </span>
          <StatusPill status={node.status} />
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm space-y-1.5">
        <p className="text-slate-500">
          Role: <span className="text-slate-700">{node.role}</span>
          {isPrimary && (
            <span className="ml-1 text-[10px] uppercase tracking-wide text-indigo-600">
              · primary
            </span>
          )}
        </p>
        <p className="text-slate-500">
          Services:{" "}
          <span className="text-slate-700">
            {(node.services ?? []).join(", ") || "—"}
          </span>
        </p>
        <p className="text-slate-500">
          Last heartbeat:{" "}
          <span className="text-slate-700">
            {fmtRelative(node.last_heartbeat_at)}
          </span>
        </p>
        {node.drained_at && (
          <p className="text-amber-700 text-xs">
            Drained {fmtRelative(node.drained_at)}
          </p>
        )}
        {!isPrimary && (
          <div className="flex justify-end gap-1.5 pt-2 border-t border-slate-100 mt-2">
            {!drained && (
              <Button size="sm" variant="ghost"
                      onClick={() => {
                        if (confirm(`Drain ${node.hostname}? It will finish in-flight calls then stop accepting new ones.`)) {
                          drain.mutate(node.id);
                        }
                      }}
                      disabled={drain.isPending}>
                Drain
              </Button>
            )}
            <Button size="sm" variant="ghost"
                    onClick={() => {
                      if (confirm(`Remove ${node.hostname} from the cluster?`)) {
                        remove.mutate(node.id);
                      }
                    }}
                    disabled={remove.isPending || (!drained && node.status !== "down")}>
              <Trash2 className="h-3.5 w-3.5" /> Remove
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function roleIcon(role: string) {
  switch (role) {
    case "gpu":     return Cpu;
    case "app":     return Server;
    case "sip":     return Headphones;
    case "primary": return Network;
    default:        return Server;
  }
}

// ---------------------------------------------------------------------------
// Add Node dialog — three steps:
//   1. Pick role + TTL → generate token
//   2. Show install command (copy)
//   3. Wait for the new node to phone home (poll /cluster/nodes)
// ---------------------------------------------------------------------------

function AddNodeDialog({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<1 | 2>(1);
  const [role, setRole] = useState<NodeRole>("gpu");
  const [label, setLabel] = useState("");
  const [ttl, setTtl] = useState(60);
  const [token, setToken] = useState<JoinTokenCreated | null>(null);
  const create = useCreateJoinToken();

  const generate = async () => {
    const t = await create.mutateAsync({ role, label, ttl_minutes: ttl });
    setToken(t);
    setStep(2);
  };

  return (
    <DialogContent className="max-w-2xl">
      {step === 1 && (
        <>
          <DialogHeader>
            <DialogTitle>Add a new node to the cluster</DialogTitle>
            <DialogDescription>
              Generate a one-time join token. Run the install command on
              the new server — it'll auto-register with this primary and
              show up in the list. Token expires after the time you set.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Node role</Label>
              <Select value={role} onValueChange={(v) => setRole(v as NodeRole)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpu">
                    GPU — runs LLM + STT + TTS (needs NVIDIA GPU)
                  </SelectItem>
                  <SelectItem value="app">
                    App — panel + workers + Session Manager (CPU only)
                  </SelectItem>
                  <SelectItem value="sip">
                    SIP — PJSIP audio gateway (CPU only)
                  </SelectItem>
                  <SelectItem value="mixed">
                    Mixed — runs everything (small clusters / dev)
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-slate-500">
                Pick <code>gpu</code> when you're scaling concurrent-call capacity. The
                rest are for splitting load on very large clusters.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Label (optional)</Label>
                <Input value={label} onChange={(e) => setLabel(e.target.value)}
                       placeholder="e.g. hetzner-gex44-de01" />
              </div>
              <div className="space-y-1.5">
                <Label>Token expires in</Label>
                <Select value={String(ttl)}
                        onValueChange={(v) => setTtl(parseInt(v, 10))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="15">15 minutes</SelectItem>
                    <SelectItem value="60">1 hour</SelectItem>
                    <SelectItem value="240">4 hours</SelectItem>
                    <SelectItem value="1440">24 hours</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={generate} disabled={create.isPending}>
              {create.isPending
                ? <><Loader2 className="h-4 w-4 animate-spin" /> Generating…</>
                : "Generate token"}
            </Button>
          </DialogFooter>
        </>
      )}

      {step === 2 && token && (
        <JoinInstructions token={token} onClose={onClose} />
      )}
    </DialogContent>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — install command + live wait for the new node
// ---------------------------------------------------------------------------

function JoinInstructions({
  token, onClose,
}: { token: JoinTokenCreated; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const { data: nodes } = useNodes();

  // Track which nodes existed before — anything new must be the joiner.
  const [baseline] = useState(() => new Set((nodes ?? []).map((n) => n.id)));
  const newNode = (nodes ?? []).find((n) => !baseline.has(n.id));

  // Auto-close 3 seconds after the new node appears + goes healthy.
  useEffect(() => {
    if (newNode && (newNode.status === "ok" || newNode.status === "running")) {
      const t = setTimeout(onClose, 3000);
      return () => clearTimeout(t);
    }
  }, [newNode, onClose]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(token.install_command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard might not be available — operator can select+copy manually
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Run this on the new server</DialogTitle>
        <DialogDescription>
          SSH into the box you want to add (Ubuntu 22.04+, root or sudo).
          Paste the command. It'll fetch the installer, register with this
          primary, and start the services for role <strong>{token.role}</strong>.
          The token is single-use and expires{" "}
          {new Date(token.expires_at).toLocaleString()}.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-3 py-2">
        <div className="relative">
          <pre className="rounded-md bg-slate-900 text-slate-100 text-xs
                          font-mono p-3 pr-20 overflow-x-auto leading-relaxed">
            {token.install_command}
          </pre>
          <Button
            type="button" size="sm" variant="secondary"
            className="absolute top-2 right-2"
            onClick={copy}
          >
            {copied ? <><Check className="h-3.5 w-3.5" /> Copied</> : "Copy"}
          </Button>
        </div>

        <p className="text-xs text-slate-500">
          The installer also asks you to copy <code>/etc/aipanel/secrets.env</code>{" "}
          from this primary to the new box. <code>scp</code> works:
          <br />
          <code className="text-[11px]">
            scp /etc/aipanel/secrets.env new-host:/etc/aipanel/secrets.env
          </code>
        </p>

        <WaitingForNode newNode={newNode} role={token.role} />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {newNode ? "Close" : "Done — I'll watch the Cluster page"}
        </Button>
      </DialogFooter>
    </>
  );
}

function WaitingForNode({
  newNode, role,
}: { newNode: any; role: string }) {
  if (!newNode) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-amber-200
                      bg-amber-50 px-3 py-2 text-sm text-amber-800">
        <Loader2 className="h-4 w-4 animate-spin shrink-0" />
        Waiting for the new {role} node to phone home…
      </div>
    );
  }
  const ready = newNode.status === "ok" || newNode.status === "running";
  return (
    <div className={
      "flex items-center gap-2 rounded-md border px-3 py-2 text-sm " +
      (ready
        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
        : "border-indigo-200 bg-indigo-50 text-indigo-800")
    }>
      {ready
        ? <Check className="h-4 w-4 shrink-0" />
        : <Loader2 className="h-4 w-4 animate-spin shrink-0" />}
      <span className="font-medium">{newNode.hostname}</span>
      <span className="text-xs">— {newNode.status}</span>
    </div>
  );
}
