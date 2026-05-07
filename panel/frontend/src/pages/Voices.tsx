import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Volume2 } from "lucide-react";
import { useCloneVoice, useDeleteVoice, useVoices } from "@/api/hooks/useVoices";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { VoiceRecorder } from "@/components/VoiceRecorder";
import { fmtRelative } from "@/lib/format";
import { canWrite } from "@/lib/permissions";
import { useAuth } from "@/auth/store";
import { cloneVoiceSchema } from "@/lib/validation";

export function Voices() {
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading } = useVoices();
  const del = useDeleteVoice();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Voices"
        description="Cloned voices used by your agents. Each is a reference clip + matching transcript."
        actions={canWrite(role) && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> Clone voice</Button>
            </DialogTrigger>
            <CloneVoiceDialog onDone={() => setOpen(false)} />
          </Dialog>
        )}
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={Volume2}
          title="No voices yet"
          description="Upload a 30 s sample to clone your first voice."
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Status</TH>
                <TH>Created</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {data!.items.map((v) => (
                <TR key={v.id}>
                  <TD className="font-medium">{v.name}</TD>
                  <TD><StatusPill status={v.status} /></TD>
                  <TD className="text-slate-500">{fmtRelative(v.created_at)}</TD>
                  <TD className="text-right">
                    {canWrite(role) && (
                      <Button
                        size="sm" variant="ghost"
                        onClick={() => {
                          if (confirm(`Delete voice "${v.name}"?`)) del.mutate(v.id);
                        }}
                      >
                        Delete
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
    </>
  );
}

function CloneVoiceDialog({ onDone }: { onDone: () => void }) {
  const clone = useCloneVoice();
  const form = useForm<{ name: string; ref_text: string }>({
    resolver: zodResolver(cloneVoiceSchema),
    defaultValues: { name: "", ref_text: "" },
  });
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"upload" | "record">("record");

  const onSubmit = async (values: { name: string; ref_text: string }) => {
    if (!file) {
      alert("Record or upload an audio sample first");
      return;
    }
    await clone.mutateAsync({ ...values, audio: file });
    onDone();
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Clone a voice</DialogTitle>
        <DialogDescription>
          Record yourself reading the sample script (30–60s), or upload an
          existing clip. The TTS server processes the result in the background.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="name">Voice name</Label>
          <Input id="name" {...form.register("name")} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ref_text">What the recording says (transcript)</Label>
          <Textarea id="ref_text" rows={3} {...form.register("ref_text")} />
        </div>

        <div className="flex gap-2 text-xs">
          <button type="button"
                  onClick={() => setMode("record")}
                  className={`px-3 py-1 rounded-md border ${
                    mode === "record"
                      ? "border-indigo-300 bg-indigo-50 text-indigo-800"
                      : "border-slate-200 text-slate-600"
                  }`}>
            Record from mic
          </button>
          <button type="button"
                  onClick={() => setMode("upload")}
                  className={`px-3 py-1 rounded-md border ${
                    mode === "upload"
                      ? "border-indigo-300 bg-indigo-50 text-indigo-800"
                      : "border-slate-200 text-slate-600"
                  }`}>
            Upload file
          </button>
        </div>

        {mode === "record" ? (
          <VoiceRecorder
            onComplete={(f) => setFile(f)}
            onCancel={() => setFile(null)}
          />
        ) : (
          <div className="space-y-1.5">
            <Label htmlFor="audio">Audio file (WAV / MP3 / M4A)</Label>
            <Input
              id="audio" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/x-m4a"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        )}

        {file && (
          <p className="text-xs text-emerald-600">
            ✓ {file.name} ready ({Math.round(file.size / 1024)} KB)
          </p>
        )}
        <p className="text-xs text-slate-500">
          Browser-mic recording captures audio at 24 kHz, mono.
        </p>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={clone.isPending}>Clone</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
