import { useState } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { Plus, Target } from "lucide-react";
import { useCampaigns, useCreateCampaign } from "@/api/hooks/useCampaigns";
import { useAuth } from "@/auth/store";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtRelative } from "@/lib/format";
import { canWrite } from "@/lib/permissions";

const METHODOLOGIES = [
  { value: "consultative", label: "Consultative" },
  { value: "spin",         label: "SPIN" },
  { value: "bant",         label: "BANT" },
  { value: "meddpicc",     label: "MEDDPICC" },
  { value: "value_based",  label: "Value-based" },
  { value: "custom",       label: "Custom" },
];

export function Campaigns() {
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading } = useCampaigns();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Reusable sales playbooks. Each campaign bundles methodology, success criteria, KB binding, and the few-shot pool mined from your own successful calls."
        actions={canWrite(role) && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> New campaign</Button>
            </DialogTrigger>
            <NewCampaignDialog onDone={() => setOpen(false)} />
          </Dialog>
        )}
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={Target}
          title="No campaigns yet"
          description="Create one to share a sales playbook across multiple agents."
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Methodology</TH>
                <TH>Status</TH>
                <TH>Few-shot</TH>
                <TH>Updated</TH>
              </TR>
            </THead>
            <TBody>
              {data!.items.map((c) => (
                <TR key={c.id}>
                  <TD>
                    <Link to={`/campaigns/${c.id}`}
                          className="font-medium text-slate-900 hover:underline">
                      {c.name}
                    </Link>
                    {c.objective && (
                      <p className="text-xs text-slate-500 mt-0.5 max-w-xl truncate">
                        {c.objective}
                      </p>
                    )}
                  </TD>
                  <TD className="text-slate-600 capitalize">
                    {c.methodology.replace("_", "-")}
                  </TD>
                  <TD><StatusPill status={c.status} /></TD>
                  <TD className="text-slate-600">
                    {c.few_shot_count} examples
                    {c.few_shot_updated_at && (
                      <span className="text-xs text-slate-400 block">
                        mined {fmtRelative(c.few_shot_updated_at)}
                      </span>
                    )}
                  </TD>
                  <TD className="text-slate-500">{fmtRelative(c.updated_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
    </>
  );
}

function NewCampaignDialog({ onDone }: { onDone: () => void }) {
  const create = useCreateCampaign();
  const form = useForm({
    defaultValues: {
      name: "",
      objective: "",
      methodology: "consultative",
      success_dispos_csv: "QUAL, XFER",
    },
  });

  const onSubmit = async (values: any) => {
    await create.mutateAsync({
      name: values.name,
      objective: values.objective,
      methodology: values.methodology,
      success_dispos: values.success_dispos_csv
        .split(",").map((s: string) => s.trim()).filter(Boolean),
    });
    onDone();
  };

  return (
    <DialogContent>
      <DialogHeader><DialogTitle>New campaign</DialogTitle></DialogHeader>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="c-name">Name</Label>
          <Input id="c-name" {...form.register("name", { required: true })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="c-obj">Objective (one sentence)</Label>
          <Textarea id="c-obj" rows={2} {...form.register("objective")} />
        </div>
        <div className="space-y-1.5">
          <Label>Methodology</Label>
          <Select
            value={form.watch("methodology")}
            onValueChange={(v) => form.setValue("methodology", v)}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {METHODOLOGIES.map((m) => (
                <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="c-dispo">Success disposition codes (comma-sep)</Label>
          <Input id="c-dispo" {...form.register("success_dispos_csv")} />
          <p className="text-xs text-slate-500">
            Calls with these dispo codes count as "won" for metrics + few-shot mining.
          </p>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>Create</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
