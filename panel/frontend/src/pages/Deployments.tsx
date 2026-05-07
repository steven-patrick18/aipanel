import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Boxes, Plus, X } from "lucide-react";
import { useAgents } from "@/api/hooks/useAgents";
import { useCampaigns } from "@/api/hooks/useCampaigns";
import { useCreateDeployment, useDeployments } from "@/api/hooks/useDeployments";
import { useVicidialServers } from "@/api/hooks/useVicidialServers";
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
import { deploymentCreateSchema } from "@/lib/validation";

export function Deployments() {
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading } = useDeployments();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Deployments"
        description="Each deployment binds an agent + voice + ViciDial credentials and logs in as a single agent."
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
          description="Wire up an agent to a ViciDial server to start handling calls."
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

interface DeploymentForm {
  agent_id: string;
  vicidial_server_id: string;
  vici_user: string;
  vici_pass: string;
  phone_login: string;
  phone_pass: string;
  campaign_id: string;
  allowed_transfer_ingroups: string[];
  aipanel_campaign_id?: string | null;
}

function NewDeploymentDialog({ onDone }: { onDone: () => void }) {
  const nav = useNavigate();
  const create = useCreateDeployment();
  const { data: agents } = useAgents({ limit: 200 });
  const { data: servers } = useVicidialServers();
  const { data: campaigns } = useCampaigns();
  const [ingroupInput, setIngroupInput] = useState("");

  const form = useForm<DeploymentForm>({
    resolver: zodResolver(deploymentCreateSchema as any),
    defaultValues: {
      agent_id: "",
      vicidial_server_id: "",
      vici_user: "",
      vici_pass: "",
      phone_login: "",
      phone_pass: "",
      campaign_id: "",
      allowed_transfer_ingroups: [],
      aipanel_campaign_id: null,
    },
  });

  const ingroups = form.watch("allowed_transfer_ingroups");

  const addIngroup = () => {
    const v = ingroupInput.trim();
    if (!v) return;
    if (ingroups.includes(v)) { setIngroupInput(""); return; }
    form.setValue("allowed_transfer_ingroups", [...ingroups, v]);
    setIngroupInput("");
  };

  const removeIngroup = (ig: string) => {
    form.setValue("allowed_transfer_ingroups", ingroups.filter((x) => x !== ig));
  };

  const submit = async (vals: DeploymentForm) => {
    const body: any = { ...vals };
    if (!body.aipanel_campaign_id) delete body.aipanel_campaign_id;
    const created = await create.mutateAsync(body);
    onDone();
    nav(`/deployments/${created.id}`);
  };

  const eligibleAgents = (agents?.items ?? []).filter(
    (a) => a.status !== "archived",
  );

  return (
    <DialogContent className="max-w-2xl">
      <DialogHeader>
        <DialogTitle>New deployment</DialogTitle>
        <DialogDescription>
          Pair an agent + voice with one ViciDial seat. The Session Manager
          will log this user into the dialler and route inbound calls to the
          AI worker. Start the deployment from its detail page.
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={form.handleSubmit(submit)}
            className="space-y-4 max-h-[65vh] overflow-y-auto pr-1">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Agent</Label>
            <Select
              value={form.watch("agent_id")}
              onValueChange={(v) => form.setValue("agent_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={
                  eligibleAgents.length === 0 ? "Create an agent first" : "Pick an agent…"
                } />
              </SelectTrigger>
              <SelectContent>
                {eligibleAgents.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name} · {a.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label>ViciDial server</Label>
            <Select
              value={form.watch("vicidial_server_id")}
              onValueChange={(v) => form.setValue("vicidial_server_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={
                  (servers?.items ?? []).length === 0
                    ? "Add a server first"
                    : "Pick a server…"
                } />
              </SelectTrigger>
              <SelectContent>
                {(servers?.items ?? []).map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} · {s.asterisk_host}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="dep-vu">ViciDial user</Label>
            <Input id="dep-vu" placeholder="agent01"
                   {...form.register("vici_user")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dep-vp">ViciDial password</Label>
            <Input id="dep-vp" type="password"
                   {...form.register("vici_pass")} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="dep-pl">Phone login</Label>
            <Input id="dep-pl" placeholder="9001"
                   {...form.register("phone_login")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dep-pp">Phone password</Label>
            <Input id="dep-pp" type="password"
                   {...form.register("phone_pass")} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="dep-cid">ViciDial campaign code</Label>
            <Input id="dep-cid" placeholder="SOLAR"
                   {...form.register("campaign_id")} />
            <p className="text-xs text-slate-500">
              The campaign code as configured in ViciDial (not the panel's
              own campaign).
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>Link to panel campaign (optional)</Label>
            <Select
              value={form.watch("aipanel_campaign_id") ?? "__none"}
              onValueChange={(v) =>
                form.setValue("aipanel_campaign_id", v === "__none" ? null : v)
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="None" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none">None</SelectItem>
                {(campaigns?.items ?? [])
                  .filter((c) => c.status !== "archived")
                  .map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Allowed transfer ingroups</Label>
          <p className="text-xs text-slate-500">
            Operators can only forward live calls into ingroups in this list.
            Leave empty to allow any ID (operator must type it manually).
          </p>
          <div className="flex gap-2">
            <Input
              placeholder="e.g. SALES, BILLING_TIER2"
              value={ingroupInput}
              onChange={(e) => setIngroupInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); addIngroup(); }
              }}
            />
            <Button type="button" variant="outline" onClick={addIngroup}>Add</Button>
          </div>
          {ingroups.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {ingroups.map((ig) => (
                <span key={ig}
                      className="inline-flex items-center gap-1 rounded-md
                                 border border-slate-200 bg-slate-50
                                 px-2 py-0.5 text-xs">
                  {ig}
                  <button type="button"
                          className="text-slate-400 hover:text-slate-700"
                          onClick={() => removeIngroup(ig)}>
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Create deployment"}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
