import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, User } from "lucide-react";
import { openSSE } from "@/api/sse";
import { Card } from "@/components/ui/card";
import { fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

interface LiveTranscriptProps {
  deploymentId: string;
}

interface TurnRow {
  ts: string;
  role: "user" | "agent" | "system";
  text: string;
  partial?: boolean;
}

export function LiveTranscript({ deploymentId }: LiveTranscriptProps) {
  const [turns, setTurns] = useState<TurnRow[]>([]);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();

    void openSSE({
      path: `/deployments/${deploymentId}/live`,
      signal: ctrl.signal,
      onOpen: () => setConnected(true),
      onError: () => setConnected(false),
      onMessage: (evt) => {
        if (!evt || typeof evt !== "object") return;
        const ts = new Date().toISOString();
        switch (evt.type) {
          case "transcript_partial":
            setTurns((prev) => {
              const next = [...prev];
              if (next.length > 0 && next[next.length - 1].partial) {
                next[next.length - 1] = {
                  ...next[next.length - 1],
                  text: String(evt.text || ""),
                };
              } else {
                next.push({
                  ts, role: "user",
                  text: String(evt.text || ""),
                  partial: true,
                });
              }
              return next;
            });
            break;
          case "transcript_final":
          case "user_speech":
            setTurns((prev) => {
              const next = prev.filter((t) => !t.partial);
              next.push({ ts, role: "user", text: String(evt.text || "") });
              return next;
            });
            break;
          case "agent_response":
          case "agent_speech":
            setTurns((prev) => [
              ...prev,
              { ts, role: "agent", text: String(evt.text || "") },
            ]);
            break;
          case "tool_call":
            setTurns((prev) => [
              ...prev,
              {
                ts, role: "system",
                text: `tool: ${evt.name ?? "?"} ${
                  evt.args ? JSON.stringify(evt.args) : ""
                }`,
              },
            ]);
            break;
          case "call_started":
            setTurns([{ ts, role: "system", text: "Call connected" }]);
            break;
          case "call_ended":
            setTurns((prev) => [
              ...prev,
              { ts, role: "system", text: `Call ended (${evt.outcome ?? "—"})` },
            ]);
            break;
          default:
            break;
        }
      },
    });

    return () => ctrl.abort();
  }, [deploymentId]);

  // Auto-scroll on new content.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns]);

  const empty = turns.length === 0;

  return (
    <Card className="p-0 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center justify-between text-xs">
        <span className="font-medium text-slate-600">Live transcript</span>
        <span
          className={cn(
            "inline-flex items-center gap-1.5",
            connected ? "text-emerald-600" : "text-slate-400",
          )}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              connected ? "bg-emerald-500 animate-pulse" : "bg-slate-300",
            )}
          />
          {connected ? "live" : "connecting…"}
        </span>
      </div>

      <div ref={scrollRef} className="h-[420px] overflow-y-auto p-4 space-y-3">
        {empty ? (
          <p className="text-center text-sm text-slate-400 mt-16">
            Waiting for call activity…
          </p>
        ) : (
          turns.map((t, i) => <Turn key={i} turn={t} />)
        )}
      </div>
    </Card>
  );
}

function Turn({ turn }: { turn: TurnRow }) {
  if (turn.role === "system") {
    return (
      <p className="text-center text-[11px] uppercase tracking-wide text-slate-400">
        {turn.text}
      </p>
    );
  }
  const isAgent = turn.role === "agent";
  return (
    <div className={cn("flex gap-2.5", isAgent ? "" : "flex-row-reverse")}>
      <div
        className={cn(
          "h-7 w-7 rounded-full grid place-items-center shrink-0",
          isAgent ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-600",
        )}
      >
        {isAgent ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
      </div>
      <div className={cn("max-w-[78%] flex flex-col", isAgent ? "items-start" : "items-end")}>
        <div
          className={cn(
            "rounded-lg px-3 py-2 text-sm",
            isAgent
              ? "bg-indigo-50 text-indigo-900"
              : "bg-slate-100 text-slate-900",
            turn.partial && "italic opacity-70",
          )}
        >
          {turn.text}
        </div>
        <span className="mt-1 text-[10px] text-slate-400">
          {fmtRelative(turn.ts)}
        </span>
      </div>
    </div>
  );
}
