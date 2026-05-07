import { Controller, useFormContext } from "react-hook-form";
import { Mic, Volume2 } from "lucide-react";
import { useVoices } from "@/api/hooks/useVoices";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { AgentCreateInput } from "@/lib/validation";

export function VoiceTab() {
  const { control } = useFormContext<AgentCreateInput>();
  const { data, isLoading } = useVoices();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Voice selection</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Cloned voice</Label>
            {isLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Controller
                name="voice_id"
                control={control}
                render={({ field }) => (
                  <Select
                    value={field.value ?? ""}
                    onValueChange={(v) => field.onChange(v || null)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="No voice selected (use TTS default)" />
                    </SelectTrigger>
                    <SelectContent>
                      {(data?.items ?? []).filter((v) => v.status === "ready").length === 0 && (
                        <div className="p-2 text-xs text-slate-500">
                          No ready voices yet. Clone one in the Voices page.
                        </div>
                      )}
                      {(data?.items ?? [])
                        .filter((v) => v.status === "ready")
                        .map((v) => (
                          <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                )}
              />
            )}
            <p className="text-xs text-slate-500">
              To clone a new voice from a 30-second sample, head to the Voices page.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>Test phrase</Label>
            <div className="flex gap-2">
              <input
                placeholder="Say something this voice will preview…"
                className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-1 text-sm"
              />
              <Button variant="secondary" type="button">
                <Volume2 className="h-4 w-4" /> Play
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              Preview hits <code>POST /api/v1/voices/&lt;id&gt;/preview</code> and streams audio.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Speaking style</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <SliderRow label="Rate"               hint="slow ↔ fast" />
          <SliderRow label="Pitch variance"     hint="flat ↔ expressive" />
          <SliderRow label="Filler frequency"   hint="never ↔ frequent" />
          <SliderRow label="Backchannel rate"   hint="silent ↔ chatty" />
          <p className="text-xs text-slate-500 pt-2 flex items-center gap-1.5">
            <Mic className="h-3 w-3" />
            Sliders save into the agent's persona JSONB.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function SliderRow({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="text-slate-400">{hint}</span>
      </div>
      <input
        type="range"
        min={0} max={100} defaultValue={50}
        className="w-full accent-indigo-600"
      />
    </div>
  );
}
