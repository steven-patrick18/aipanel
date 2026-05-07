import { useEffect, useRef, useState } from "react";
import {
  Bot, CheckCircle2, Circle, Loader2, Mic, Save, Send,
  ThumbsDown, ThumbsUp, Trash2, Upload, User,
} from "lucide-react";
import {
  useAgentCapability,
  useAgentChat,
  useDeleteTrainingRecording,
  useSaveTrainingChat,
  useSaveTrainingScript,
  useTrainingRecordings,
  useTrainingScript,
  useUploadTrainingRecording,
} from "@/api/hooks/useTraining";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { fmtRelative } from "@/lib/format";

/**
 * One screen, four panels — everything an operator needs to train an
 * agent without touching the other tabs.
 *
 *   1. Capability — single number telling you how trained the agent is
 *   2. Script    — paste the call script as one block
 *   3. Recordings — upload real call recordings
 *   4. Chat      — talk to the agent, save good answers as training
 */
export function TrainingTab({ agentId }: { agentId: string }) {
  return (
    <div className="space-y-6">
      <CapabilityCard agentId={agentId} />
      <ScriptCard agentId={agentId} />
      <RecordingsCard agentId={agentId} />
      <ChatCard agentId={agentId} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 1. Capability
// ---------------------------------------------------------------------------

function CapabilityCard({ agentId }: { agentId: string }) {
  const { data, isLoading } = useAgentCapability(agentId);

  if (isLoading || !data) {
    return <Card><CardContent className="py-6"><Skeleton className="h-12 w-full" /></CardContent></Card>;
  }

  const { score, breakdown } = data;
  const tone =
    score >= 80 ? "bg-emerald-500" :
    score >= 50 ? "bg-indigo-500" :
    score >= 25 ? "bg-amber-500" : "bg-slate-400";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <span>Agent capability</span>
          <span className="text-2xl font-semibold tabular-nums">{score}%</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
          <div
            className={`h-full ${tone} transition-all duration-500`}
            style={{ width: `${score}%` }}
          />
        </div>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
          {breakdown.map((b) => (
            <li key={b.key} className="flex items-center gap-2">
              {b.done
                ? <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                : <Circle className="h-4 w-4 text-slate-300 shrink-0" />}
              <span className={b.done ? "text-slate-700" : "text-slate-500"}>
                {b.label}
              </span>
              <span className="ml-auto text-xs text-slate-400 tabular-nums">
                {b.points}/{b.max}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// 2. Script — paste one block, hit save.
// ---------------------------------------------------------------------------

function ScriptCard({ agentId }: { agentId: string }) {
  const { data, isLoading } = useTrainingScript(agentId);
  const save = useSaveTrainingScript(agentId);
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);

  // Hydrate the textarea from the server.
  useEffect(() => {
    if (data && !dirty) setText(data.script);
  }, [data, dirty]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Script</CardTitle>
        <p className="text-sm text-slate-500">
          Paste your full call script here. The agent reads it as instructions
          for every call. Edit anytime — it takes effect on the next call.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <Textarea
            rows={12}
            placeholder={
              "Hi, this is Maya from Fixit support, how can I help today?\n\n" +
              "When the customer mentions an order, ask for the order number.\n" +
              "For damaged items, offer a replacement under warranty.\n" +
              "Always close with: \"Thanks for choosing Fixit, have a great day.\""
            }
            value={text}
            onChange={(e) => { setText(e.target.value); setDirty(true); }}
            className="font-mono text-sm"
          />
        )}
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500">
            {text.length} characters
          </p>
          <Button
            type="button"
            disabled={!dirty || save.isPending}
            onClick={async () => {
              await save.mutateAsync(text);
              setDirty(false);
            }}
          >
            <Save className="h-4 w-4" />
            {save.isPending ? "Saving…" : "Save script"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// 3. Recordings — drop audio in, agent learns from real calls.
// ---------------------------------------------------------------------------

function RecordingsCard({ agentId }: { agentId: string }) {
  const { data: recordings, isLoading } = useTrainingRecordings(agentId);
  const upload = useUploadTrainingRecording(agentId);
  const del = useDeleteTrainingRecording(agentId);
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const submit = async () => {
    if (!file) return;
    await upload.mutateAsync({ file });
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Call recordings</CardTitle>
        <p className="text-sm text-slate-500">
          Upload recordings of real customer calls. We transcribe each one
          and the agent learns the patterns — tone, pacing, answers that
          worked. Add as many as you have.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-end gap-2">
          <Input
            ref={fileInput}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.opus,.ogg,.flac"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="flex-1"
          />
          <Button
            type="button"
            disabled={!file || upload.isPending}
            onClick={submit}
          >
            {upload.isPending
              ? <><Loader2 className="h-4 w-4 animate-spin" /> Uploading…</>
              : <><Upload className="h-4 w-4" /> Upload</>}
          </Button>
        </div>

        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : (recordings ?? []).length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-4">
            No recordings uploaded yet.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {(recordings ?? []).map((r) => (
              <li key={r.id}
                  className="flex items-center gap-3 rounded-md border border-slate-200 px-3 py-2 text-sm">
                <Mic className="h-4 w-4 text-slate-400 shrink-0" />
                <span className="font-medium truncate flex-1">{r.filename}</span>
                <span className="text-xs text-slate-500 shrink-0">
                  {Math.round(r.size_bytes / 1024)} KB
                </span>
                <RecStatus status={r.status} />
                <span className="text-xs text-slate-400 shrink-0">
                  {fmtRelative(r.uploaded_at)}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    if (confirm(`Delete "${r.filename}"?`)) del.mutate(r.id);
                  }}
                  className="text-slate-400 hover:text-red-600 shrink-0"
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RecStatus({ status }: { status: string }) {
  const cls = {
    queued:       "bg-slate-100 text-slate-700",
    transcribing: "bg-amber-100 text-amber-800",
    ready:        "bg-emerald-100 text-emerald-800",
    error:        "bg-red-100 text-red-800",
  }[status] || "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase ${cls}`}>
      {status !== "ready" && status !== "error" &&
        <Loader2 className="h-2.5 w-2.5 animate-spin" />}
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// 4. Chat — talk to the agent + save good answers as training.
// ---------------------------------------------------------------------------

interface ChatTurn {
  user: string;
  agent: string;
  saved: boolean;
  dismissed: boolean;
}

function ChatCard({ agentId }: { agentId: string }) {
  const chat = useAgentChat(agentId);
  const saveChat = useSaveTrainingChat(agentId);
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom on new turn.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const msg = input.trim();
    if (!msg) return;
    setInput("");
    const reply = await chat.mutateAsync(msg);
    setHistory((h) => [...h, { user: msg, agent: reply, saved: false, dismissed: false }]);
  };

  const saveTurn = async (idx: number) => {
    const t = history[idx];
    await saveChat.mutateAsync({ user: t.user, agent: t.agent });
    setHistory((h) => h.map((x, i) => i === idx ? { ...x, saved: true } : x));
  };

  const dismissTurn = (idx: number) => {
    setHistory((h) => h.map((x, i) => i === idx ? { ...x, dismissed: true } : x));
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Chat with the agent</CardTitle>
        <p className="text-sm text-slate-500">
          Try a question a real customer might ask. Thumbs-up the answers
          you'd want the agent to repeat — those become training examples.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          ref={scrollRef}
          className="max-h-[360px] min-h-[120px] overflow-y-auto rounded-md border border-slate-200 bg-slate-50/50 p-3 space-y-3"
        >
          {history.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-4">
              Type something below to start the conversation.
            </p>
          ) : (
            history.map((t, i) => (
              <div key={i} className="space-y-1.5">
                <Bubble role="user" text={t.user} />
                <Bubble role="agent" text={t.agent} />
                {!t.saved && !t.dismissed && (
                  <div className="flex justify-end gap-1.5 pt-0.5">
                    <button
                      type="button"
                      onClick={() => saveTurn(i)}
                      disabled={saveChat.isPending}
                      className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 px-2 py-1 text-xs hover:bg-emerald-100"
                    >
                      <ThumbsUp className="h-3 w-3" /> Save as training
                    </button>
                    <button
                      type="button"
                      onClick={() => dismissTurn(i)}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white text-slate-600 px-2 py-1 text-xs hover:bg-slate-50"
                    >
                      <ThumbsDown className="h-3 w-3" /> Dismiss
                    </button>
                  </div>
                )}
                {t.saved && (
                  <p className="text-right text-[11px] text-emerald-600">
                    ✓ saved as training
                  </p>
                )}
              </div>
            ))
          )}
          {chat.isPending && (
            <Bubble role="agent" text="…" />
          )}
        </div>

        <form onSubmit={send} className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything a customer might ask…"
            disabled={chat.isPending}
          />
          <Button type="submit" disabled={chat.isPending || !input.trim()}>
            <Send className="h-4 w-4" /> Send
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function Bubble({ role, text }: { role: "user" | "agent"; text: string }) {
  const isUser = role === "user";
  return (
    <div className={`flex gap-2 items-start ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`h-6 w-6 rounded-full grid place-items-center shrink-0 ${
        isUser ? "bg-slate-200 text-slate-700" : "bg-indigo-100 text-indigo-700"
      }`}>
        {isUser ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
      </div>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
        isUser ? "bg-white border border-slate-200" : "bg-indigo-50 text-indigo-900"
      }`}>
        {text}
      </div>
    </div>
  );
}
