import { useRef, useState } from "react";
import { Loader2, Mic, Trash2, Upload } from "lucide-react";
import {
  useDeleteTrainingRecording,
  useTrainingRecordings,
  useUploadTrainingRecording,
} from "@/api/hooks/useTraining";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtRelative } from "@/lib/format";

/**
 * Training tab — operator uploads real conversation audio. The backend
 * transcribes each recording and feeds the resulting turn pairs into the
 * agent's few-shot pool, so the LLM learns to imitate what a real human
 * did. No transcript-marking, no manual entry — just upload audio.
 */
export function TrainingTab({ agentId }: { agentId: string }) {
  const { data: recordings, isLoading } = useTrainingRecordings(agentId);
  const upload = useUploadTrainingRecording(agentId);
  const del = useDeleteTrainingRecording(agentId);

  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const submit = async () => {
    if (!file) return;
    await upload.mutateAsync({ file, label: label.trim() || undefined });
    setFile(null);
    setLabel("");
    if (fileInput.current) fileInput.current.value = "";
  };

  const total = (recordings ?? []).length;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Mic className="h-4 w-4 text-indigo-600" />
            Upload a real call recording
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-slate-600">
            Drop a recording of a real conversation — best calls from your
            top human agents. We transcribe it and feed the patterns into
            this agent so it picks up tone, pacing, and the moves that
            actually convert. Repeat for as many calls as you have.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-[1fr_300px_auto] gap-3 items-end">
            <div className="space-y-1.5">
              <Label htmlFor="rec-file">Audio file</Label>
              <Input
                id="rec-file"
                ref={fileInput}
                type="file"
                accept="audio/*,.wav,.mp3,.m4a,.opus,.ogg,.flac"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rec-label">Label (optional)</Label>
              <Input
                id="rec-label"
                placeholder="e.g. Best objection handling, March"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
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

          {file && (
            <p className="text-xs text-emerald-600">
              ✓ {file.name} ready ({Math.round(file.size / 1024)} KB)
            </p>
          )}
          <p className="text-xs text-slate-500">
            Accepts WAV, MP3, M4A, OPUS, OGG, FLAC. Anything the
            transcription server can decode (faster-whisper, large-v3).
          </p>
        </CardContent>
      </Card>

      <Card className="p-0">
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span>Training recordings</span>
            <span className="text-xs font-normal text-slate-500">
              {total} {total === 1 ? "recording" : "recordings"}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : total === 0 ? (
            <p className="text-sm text-slate-500">
              No recordings yet. Upload one above and the agent will start
              learning from it on the next call.
            </p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Filename</TH>
                  <TH>Label</TH>
                  <TH>Size</TH>
                  <TH>Status</TH>
                  <TH>Uploaded</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {(recordings ?? []).map((r) => (
                  <TR key={r.id}>
                    <TD className="font-medium break-all">{r.filename}</TD>
                    <TD className="text-slate-600">{r.label || "—"}</TD>
                    <TD className="text-slate-500">
                      {Math.round(r.size_bytes / 1024)} KB
                    </TD>
                    <TD>
                      <RecordingStatus status={r.status} />
                    </TD>
                    <TD className="text-slate-500">{fmtRelative(r.uploaded_at)}</TD>
                    <TD className="text-right">
                      <Button
                        size="sm" variant="ghost"
                        onClick={() => {
                          if (confirm(`Delete "${r.filename}"?`)) del.mutate(r.id);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Delete
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RecordingStatus({ status }: { status: string }) {
  const cls = {
    queued:       "bg-slate-100 text-slate-700",
    transcribing: "bg-amber-100 text-amber-800",
    ready:        "bg-emerald-100 text-emerald-800",
    error:        "bg-red-100 text-red-800",
  }[status] || "bg-slate-100 text-slate-700";
  const label = status === "ready" ? "ready"
              : status === "queued" ? "queued"
              : status === "transcribing" ? "transcribing"
              : status === "error" ? "error" : status;
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ${cls}`}>
      {status !== "ready" && status !== "error" && (
        <Loader2 className="h-3 w-3 animate-spin" />
      )}
      {label}
    </span>
  );
}
