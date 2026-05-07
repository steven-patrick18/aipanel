import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { FormProvider, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { PhoneCall, Save, Target } from "lucide-react";
import {
  useAgent, usePromoteAgent, useTestCall, useUpdateAgent,
} from "@/api/hooks/useAgents";
import { useCampaigns } from "@/api/hooks/useCampaigns";
import { useDeployments } from "@/api/hooks/useDeployments";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { PersonaTab } from "@/components/AgentEditor/PersonaTab";
import { VoiceTab } from "@/components/AgentEditor/VoiceTab";
import { ScriptTab } from "@/components/AgentEditor/ScriptTab";
import { ScenariosTab } from "@/components/AgentEditor/ScenariosTab";
import { KBTab } from "@/components/AgentEditor/KBTab";
import { TrainingTab } from "@/components/AgentEditor/TrainingTab";
import { agentCreateSchema, type AgentCreateInput } from "@/lib/validation";
import { canWrite } from "@/lib/permissions";
import { useAuth } from "@/auth/store";

export function AgentDetail() {
  const { id } = useParams<{ id: string }>();
  const role = useAuth((s) => s.user?.role);
  const { data: agent, isLoading } = useAgent(id);
  const { data: campaignsPage } = useCampaigns();
  const update = useUpdateAgent(id!);
  const promote = usePromoteAgent();

  const form = useForm<AgentCreateInput>({
    resolver: zodResolver(agentCreateSchema),
    defaultValues: emptyAgent(),
  });

  useEffect(() => {
    if (!agent) return;
    form.reset({
      name: agent.name,
      language: agent.language,
      voice_id: agent.voice_id ?? null,
      kb_collection_id: agent.kb_collection_id ?? null,
      persona: { ...emptyAgent().persona, ...(agent.persona as any) },
      script: { ...emptyAgent().script, ...(agent.script as any) },
      scenario_tree: (agent.scenario_tree as any) ?? { rules: [] },
    });
  }, [agent]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading || !agent) return <LoadingSpinner />;

  const writeable = canWrite(role);

  const onSubmit = (values: AgentCreateInput) => update.mutateAsync(values);

  return (
    <FormProvider {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <PageHeader
          title={agent.name}
          description={`Agent · ${agent.language} · last updated ${new Date(agent.updated_at).toLocaleString()}`}
          actions={
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 text-sm">
                <Target className="h-4 w-4 text-slate-400" />
                <Select
                  value={agent.campaign_id ?? "__none"}
                  onValueChange={(v) =>
                    update.mutate({ campaign_id: v === "__none" ? null : v } as any)
                  }
                  disabled={!writeable}
                >
                  <SelectTrigger className="h-9 w-[200px]">
                    <SelectValue placeholder="No campaign linked" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none">No campaign</SelectItem>
                    {(campaignsPage?.items ?? [])
                      .filter((c) => c.status !== "archived")
                      .map((c) => (
                        <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
              <StatusPill status={agent.status} />
              {writeable && agent.status === "draft" && (
                <Button
                  type="button" variant="secondary"
                  onClick={() => promote.mutate(agent.id)}
                  disabled={promote.isPending}
                >
                  Promote to ready
                </Button>
              )}
              {writeable && agent.status !== "draft" && (
                <TestCallButton agentId={agent.id} />
              )}
              {writeable && (
                <Button type="submit" disabled={update.isPending}>
                  <Save className="h-4 w-4" /> Save
                </Button>
              )}
            </div>
          }
        />

        <Tabs defaultValue="persona">
          <TabsList>
            <TabsTrigger value="persona">Persona</TabsTrigger>
            <TabsTrigger value="voice">Voice</TabsTrigger>
            <TabsTrigger value="script">Script</TabsTrigger>
            <TabsTrigger value="scenarios">Scenarios</TabsTrigger>
            <TabsTrigger value="kb">Knowledge base</TabsTrigger>
            <TabsTrigger value="training">Training</TabsTrigger>
          </TabsList>

          <TabsContent value="persona"><PersonaTab /></TabsContent>
          <TabsContent value="voice"><VoiceTab /></TabsContent>
          <TabsContent value="script"><ScriptTab /></TabsContent>
          <TabsContent value="scenarios"><ScenariosTab /></TabsContent>
          <TabsContent value="kb"><KBTab /></TabsContent>
          <TabsContent value="training"><TrainingTab agentId={agent.id} /></TabsContent>
        </Tabs>
      </form>
    </FormProvider>
  );
}

function TestCallButton({ agentId }: { agentId: string }) {
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [deploymentId, setDeploymentId] = useState<string>("");
  const { data: deployments } = useDeployments();
  const dial = useTestCall(agentId);

  // Only show deployments tied to this agent that are in a callable state.
  const eligible = (deployments?.items ?? []).filter(
    (d) =>
      d.agent_id === agentId &&
      ["running", "ready", "paused"].includes(d.status),
  );

  const submit = async () => {
    if (!phone.trim()) return;
    await dial.mutateAsync({
      phone_number: phone.trim(),
      deployment_id: deploymentId || undefined,
    });
    setOpen(false);
    setPhone("");
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button
        type="button" variant="secondary"
        onClick={() => setOpen(true)}
        disabled={eligible.length === 0}
        title={
          eligible.length === 0
            ? "Start a deployment for this agent first"
            : "Place a test call"
        }
      >
        <PhoneCall className="h-4 w-4" /> Test call
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Place a test call</DialogTitle>
          <DialogDescription>
            ViciDial will dial this number from the chosen agent seat.
            When the leg connects, the worker takes over and runs the
            agent script — giving you a live end-to-end test.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tc-phone">Phone number to dial</Label>
            <Input
              id="tc-phone" placeholder="+15551234567" autoFocus
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
            <p className="text-xs text-slate-500">
              E.164 preferred (with country code). Whatever ViciDial accepts works.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Use deployment</Label>
            <Select value={deploymentId || "auto"}
                    onValueChange={(v) => setDeploymentId(v === "auto" ? "" : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Pick automatically</SelectItem>
                {eligible.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.vici_user} · {d.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type="button"
                  disabled={dial.isPending || !phone.trim()}
                  onClick={submit}>
            {dial.isPending ? "Dialing…" : "Dial"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function emptyAgent(): AgentCreateInput {
  return {
    name: "",
    language: "en",
    voice_id: null,
    kb_collection_id: null,
    persona: {
      name: "",
      age_range: "30-40",
      gender: "neutral",
      accent: "neutral US",
      backstory: "",
      description: "",
      guidelines: "",
      disclosure_response: "",
    },
    script: {
      opening_variants: [""],
      sections: [],
      closing: "",
      objections: [],
    },
    scenario_tree: { rules: [] },
  };
}
