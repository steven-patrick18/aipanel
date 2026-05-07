import { useState } from "react";
import { Link } from "react-router-dom";
import { Bot, FileText, Mic, Plus, Trash2, User } from "lucide-react";
import {
  useAddTrainingExample, useDeleteTrainingExample, useTrainingExamples,
} from "@/api/hooks/useTraining";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { fmtRelative } from "@/lib/format";

/**
 * Training tab — two ways to feed the agent examples it should imitate:
 *
 *   1. **Script-based**: type a `{user, agent}` pair you want the model
 *      to copy when it hears something similar. Fast for codifying a
 *      good rebuttal you already know works.
 *
 *   2. **Recording-based**: from a real call's detail page, mark a
 *      transcript turn-pair as exemplary. The recording stays attached
 *      so anyone reviewing the example can hear how the human said it.
 *
 * Both go into the same `training_examples` list on the agent — the
 * worker injects them as in-context few-shot examples on every LLM call,
 * in addition to the campaign-wide mined pool.
 */
export function TrainingTab({ agentId }: { agentId: string }) {
  const { data: examples, isLoading } = useTrainingExamples(agentId);
  const del = useDeleteTrainingExample(agentId);
  const [open, setOpen] = useState(false);

  const manual = (examples ?? []).filter((e) => e.kind === "manual");
  const fromCalls = (examples ?? []).filter((e) => e.kind === "call");

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <InfoCard
          icon={FileText}
          title="Script-based training"
          body={
            <>
              Type the user's line and the response you'd want from the
              agent. Use this for objection rebuttals or scripted moves
              you already know convert.
            </>
          }
          action={
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button size="sm"><Plus className="h-3.5 w-3.5" /> Add example</Button>
              </DialogTrigger>
              <AddExampleDialog
                agentId={agentId}
                onDone={() => setOpen(false)}
              />
            </Dialog>
          }
        />
        <InfoCard
          icon={Mic}
          title="Recording-based training"
          body={
            <>
              Open any call from <Link to="/calls" className="text-indigo-600 hover:underline">Calls</Link>{" "}
              and use <strong>Mark as exemplar</strong> on the turn that
              landed well. The recording stays attached for review.
            </>
          }
          action={null}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Training examples</span>
            <span className="text-xs font-normal text-slate-500">
              {(examples ?? []).length} total
              {fromCalls.length > 0 && ` · ${fromCalls.length} from recorded calls`}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (examples ?? []).length === 0 ? (
            <p className="text-sm text-slate-500">
              No examples yet. Use the buttons above to add the first one.
              The agent will start mimicking these on the next call.
            </p>
          ) : (
            <ul className="space-y-3">
              {[...manual, ...fromCalls].map((ex) => (
                <li key={ex.id}
                    className="rounded-md border border-slate-200 p-3 text-sm">
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2 text-xs">
                      {ex.kind === "call" ? (
                        <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">
                          <Mic className="h-3 w-3" /> from call
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded bg-indigo-50 px-1.5 py-0.5 text-indigo-700">
                          <FileText className="h-3 w-3" /> manual
                        </span>
                      )}
                      <span className="text-slate-400">
                        {fmtRelative(ex.added_at)}
                      </span>
                      {ex.call_id && (
                        <Link
                          to={`/calls/${ex.call_id}`}
                          className="text-indigo-600 hover:underline text-xs"
                        >
                          open call →
                        </Link>
                      )}
                    </div>
                    <Button
                      size="sm" variant="ghost"
                      onClick={() => {
                        if (confirm("Remove this training example?")) {
                          del.mutate(ex.id);
                        }
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  <Turn role="user" text={ex.user} />
                  <Turn role="agent" text={ex.agent} />
                  {ex.notes && (
                    <p className="mt-2 text-xs text-slate-500 italic">
                      Note: {ex.notes}
                    </p>
                  )}
                  {ex.recording_path && (
                    <p className="mt-1 text-[10px] text-slate-400 font-mono break-all">
                      {ex.recording_path}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function InfoCard({
  icon: Icon, title, body, action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: React.ReactNode;
  action: React.ReactNode | null;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-indigo-600" />
          <CardTitle className="text-sm">{title}</CardTitle>
        </div>
        {action}
      </CardHeader>
      <CardContent className="text-xs text-slate-600 leading-relaxed">
        {body}
      </CardContent>
    </Card>
  );
}

function Turn({ role, text }: { role: "user" | "agent"; text: string }) {
  const isUser = role === "user";
  return (
    <div className="flex gap-2 items-start mb-1.5">
      <div className={`h-6 w-6 rounded-full grid place-items-center shrink-0 ${
        isUser ? "bg-slate-100 text-slate-600" : "bg-indigo-100 text-indigo-700"
      }`}>
        {isUser ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
      </div>
      <p className={`flex-1 text-sm ${isUser ? "text-slate-700" : "text-indigo-900"}`}>
        {text}
      </p>
    </div>
  );
}

function AddExampleDialog({
  agentId, onDone,
}: { agentId: string; onDone: () => void }) {
  const add = useAddTrainingExample(agentId);
  const [user, setUser] = useState("");
  const [agent, setAgent] = useState("");
  const [notes, setNotes] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user.trim() || !agent.trim()) return;
    await add.mutateAsync({ user: user.trim(), agent: agent.trim(), notes });
    onDone();
    setUser(""); setAgent(""); setNotes("");
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Add a training example</DialogTitle>
        <DialogDescription>
          The agent will see this pair as an in-context example next time
          the user says something similar. Be specific — "What does it
          cost?" beats "questions about price."
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="ex-user">User says</Label>
          <Textarea id="ex-user" rows={2}
                    placeholder="What does this actually cost?"
                    value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ex-agent">Agent should respond</Label>
          <Textarea id="ex-agent" rows={3}
                    placeholder="Most installs run twenty to thirty thousand…"
                    value={agent} onChange={(e) => setAgent(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ex-notes">Why is this a good example? (optional)</Label>
          <Input id="ex-notes" placeholder="Acknowledge cost, then anchor on rebates"
                 value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit"
                  disabled={add.isPending || !user.trim() || !agent.trim()}>
            {add.isPending ? "Adding…" : "Add example"}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
