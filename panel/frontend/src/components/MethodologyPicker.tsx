import { useEffect, useState } from "react";
import { Check, Sparkles } from "lucide-react";
import { useMethodologies, useMethodology } from "@/api/hooks/useMethodologies";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { CampaignMethodology } from "@/lib/types";

interface MethodologyPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  current: CampaignMethodology;
  onSelect: (key: CampaignMethodology) => void;
}

export function MethodologyPicker({
  open, onOpenChange, current, onSelect,
}: MethodologyPickerProps) {
  const { data: catalog, isLoading } = useMethodologies();
  const [selected, setSelected] = useState<CampaignMethodology>(current);
  useEffect(() => { if (open) setSelected(current); }, [open, current]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-500" />
            Pick a sales methodology
          </DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-[260px_1fr] gap-4 max-h-[60vh]">
          <div className="overflow-y-auto pr-1 space-y-1.5">
            {isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              (catalog ?? []).map((m) => (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => setSelected(m.key)}
                  className={cn(
                    "w-full text-left rounded-md border px-3 py-2 transition-colors",
                    selected === m.key
                      ? "border-indigo-300 bg-indigo-50"
                      : "border-slate-200 bg-white hover:bg-slate-50",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm text-slate-900">
                      {m.name}
                    </span>
                    {current === m.key && (
                      <Check className="h-3.5 w-3.5 text-emerald-500" />
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">
                    {m.tagline}
                  </p>
                </button>
              ))
            )}
          </div>

          <div className="overflow-y-auto pl-2 border-l border-slate-200">
            <MethodologyPreview methodologyKey={selected} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => { onSelect(selected); onOpenChange(false); }}
            disabled={selected === current}
          >
            Use this methodology
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MethodologyPreview({ methodologyKey }: { methodologyKey: string }) {
  const { data, isLoading } = useMethodology(methodologyKey);
  if (isLoading || !data) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="space-y-4 text-sm pr-2">
      <div>
        <h3 className="text-base font-semibold text-slate-900">{data.name}</h3>
        <p className="text-slate-500 mt-1">{data.tagline}</p>
      </div>

      <div>
        <p className="text-xs uppercase tracking-wide text-slate-400 mb-1">
          When to use
        </p>
        <p className="text-slate-700">{data.when_to_use}</p>
      </div>

      <div>
        <p className="text-xs uppercase tracking-wide text-slate-400 mb-1">
          What goes into the LLM system prompt
        </p>
        <pre className="rounded-md bg-slate-50 border border-slate-200 p-3 text-[11px] leading-snug text-slate-700 whitespace-pre-wrap font-mono max-h-[180px] overflow-y-auto">
{data.system_prompt}
        </pre>
      </div>

      {data.stages.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400 mb-1">
            Call stages
          </p>
          <ol className="space-y-1.5">
            {data.stages.map((s, i) => (
              <li key={i} className="text-slate-700">
                <span className="font-medium">{i + 1}. {s.name}</span>
                <span className="text-slate-500"> — {s.goal}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {data.priority_signals.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400 mb-1">
            Listen for (success signals)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.priority_signals.map((s, i) => (
              <Badge key={i} variant="success">{s}</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
