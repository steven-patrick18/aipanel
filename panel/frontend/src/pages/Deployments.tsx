import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Boxes, Plus, X } from "lucide-react";
import { useAgents } from "@/api/hooks/useAgents";
import { useCreateDeployment, useDeployments } from "@/api/hooks/useDeployments";
import {
  useViciCampaigns,
  useViciIngroups,
  useVicidialServers,
} from "@/api/hooks/useVicidialServers";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { useAuth } from "@/auth/store";
import { canWrite } from "@/lib/permissions";
import { fmtRelative } from "@/lib/format";

export function Deployments() {
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading } = useDeployments();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Deployments"
        description="Pair an agent with a ViciDial seat. The Session Manager logs in for you and routes calls into the AI worker."
        actions={canWrite(role) && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> New deployment</Button>
            </DialogTrigger>
            <NewDeploymentDialog onDone={() => setOpen(false)} />
          </Dialog>
        )}
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={Boxes}
          title="No deployments yet"
          description="Add a ViciDial server first, then create a deployment to bind an agent to it."
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Vici user</TH>
                <TH>Phone login</TH>
                <TH>Campaign</TH>
                <TH>Status</TH>
                <TH>Last heartbeat</TH>
              </TR>
            </THead>
            <TBody>
              {data!.items.map((d) => (
                <TR key={d.id}>
                  <TD>
                    <Link
                      to={`/deployments/${d.id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {d.vici_user}
                    </Link>
                  </TD>
                  <TD className="text-slate-600">{d.phone_login}</TD>
                  <TD className="text-slate-600">{d.campaign_id}</TD>
                  <TD><StatusPill status={d.status} /></TD>
                  <TD className="text-slate-500">{fmtRelative(d.last_heartbeat_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
    </>
  );
}

function NewDeploymentDialog({ onDone }: { onDone: () => void }) {
  const nav = useNavigate();
  const create = useCreateDeployment();
  const { data: agents, isLoading: agentsLoading } = useAgents({ limit: 200 });
  const { data: servers, isLoading: serversLoading } = useVicidialServers();

  const [agentId, setAgentId] = useState("");
  const [serverId, setServerId] = useState("");
  const [viciUser, setViciUser] = useState("");
  const [viciPass, setViciPass] = useState("");
  const [phoneLogin, setPhoneLogin] = useState("");
  const [phonePass, setPhonePass] = useState("");
  const [campaign, setCampaign] = useState("");
  const [ingroups, setIngroups] = useState<string[]>([]);

  // Discovery: as soon as a server is picked, fetch its campaigns + ingroups.
  const { data: viciCampaigns, isLoading: campaignsLoading } =
    useViciCampaigns(serverId || undefined);
  const { data: viciIngroups, isLoading: ingroupsLoading } =
    useViciIngroups(serverId || undefined);

  // Reset campaign + ingroups when the server changes.
  useEffect(() => {
    setCampaign("");
    setIngroups([]);
  }, [serverId]);

  // Default ingroups to "all available" once they load — operators can
  // narrow it down, but having something pre-populated removes friction.
  useEffect(() => {
    if (viciIngroups && ingroups.length === 0) {
      setIngroups(viciIngroups.map((g) => g.code));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viciIngroups]);

  const toggleIngroup = (code: string) => {
    setIngroups((cur) =>
      cur.includes(code) ? cur.filter((x) => x !== code) : [...cur, code],
    );
  };

  const eligibleAgents = (agents?.items ?? []).filter(
    (a) => a.status !== "archived",
  );

  const ready = agentId && serverId && viciUser && viciPass &&
                phoneLogin && phonePass && campaign;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    const created = await create.mutateAsync({
      agent_id: agentId,
      vicidial_server_id: serverId,
      vici_user: viciUser,
      vici_pass: viciPass,
      phone_login: phoneLogin,
      phone_pass: phonePass,
      campaign_id: campaign,
      allowed_transfer_ingroups: ingroups,
    });
    onDone();
    nav(`/deployments/${created.id}`);
  };

  return (
    <DialogContent className="max-w-2xl">
      <DialogHeader>
        <DialogTitle>New deployment</DialogTitle>
        <DialogDescription>
          Pick an agent + a ViciDial seat. Campaigns and transfer ingroups
          are loaded straight from the dialler — no need to type codes by
          hand.
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={submit}
            className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">

        <Row label="Agent">
          {agentsLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : eligibleAgents.length === 0 ? (
            <p className="text-xs text-amber-700 px-1">
              No agents yet — <Link to="/agents" className="underline">create one first</Link>.
            </p>
          ) : (
            <Select value={agentId} onValueChange={setAgentId}>
              <SelectTrigger><SelectValue placeholder="Pick an agent…" /></SelectTrigger>
              <SelectContent>
                {eligibleAgents.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name} · {a.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Row>

        <Row label="ViciDial server">
          {serversLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : (servers?.items ?? []).length === 0 ? (
            <p className="text-xs text-amber-700 px-1">
              No ViciDial servers yet — <Link to="/vicidial-servers" className="underline">add one first</Link>.
            </p>
          ) : (
            <Select value={serverId} onValueChange={setServerId}>
              <SelectTrigger><SelectValue placeholder="Pick a server…" /></SelectTrigger>
              <SelectContent>
                {(servers?.items ?? []).map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} · {s.asterisk_host}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Row>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Row label="ViciDial user">
            <Input placeholder="agent01" value={viciUser}
                   onChange={(e) => setViciUser(e.target.value)} />
          </Row>
          <Row label="ViciDial password">
            <Input type="password" value={viciPass}
                   onChange={(e) => setViciPass(e.target.value)} />
          </Row>
          <Row label="Phone login">
            <Input placeholder="9001" value={phoneLogin}
                   onChange={(e) => setPhoneLogin(e.target.value)} />
          </Row>
          <Row label="Phone password">
            <Input type="password" value={phonePass}
                   onChange={(e) => setPhonePass(e.target.value)} />
          </Row>
        </div>

        <Row label="Campaign">
          {!serverId ? (
            <p className="text-xs text-slate-500 px-1">Pick a server first.</p>
          ) : campaignsLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : (viciCampaigns ?? []).length === 0 ? (
            <p className="text-xs text-amber-700 px-1">
              This server doesn't expose any campaigns. Check the AMI / web
              login on the ViciDial servers page.
            </p>
          ) : (
            <Select value={campaign} onValueChange={setCampaign}>
              <SelectTrigger><SelectValue placeholder="Pick a campaign…" /></SelectTrigger>
              <SelectContent>
                {(viciCampaigns ?? []).map((c) => (
                  <SelectItem key={c.code} value={c.code}>
                    {c.name} <span className="text-slate-400">· {c.code}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Row>

        <Row label="Allowed transfer ingroups">
          {!serverId ? (
            <p className="text-xs text-slate-500 px-1">Pick a server first.</p>
          ) : ingroupsLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : (viciIngroups ?? []).length === 0 ? (
            <p className="text-xs text-amber-700 px-1">
              This server has no inbound groups configured.
            </p>
          ) : (
            <>
              <p className="text-xs text-slate-500 mb-2">
                Operators can only forward live calls into the ones you tick.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {(viciIngroups ?? []).map((g) => {
                  const on = ingroups.includes(g.code);
                  return (
                    <button
                      key={g.code}
                      type="button"
                      onClick={() => toggleIngroup(g.code)}
                      className={
                        "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition " +
                        (on
                          ? "border-indigo-300 bg-indigo-50 text-indigo-800"
                          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")
                      }
                    >
                      {on && <X className="h-3 w-3" />}
                      {g.name} <span className="text-slate-400">· {g.code}</span>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </Row>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={!ready || create.isPending}>
            {create.isPending ? "Saving…" : "Create deployment"}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
