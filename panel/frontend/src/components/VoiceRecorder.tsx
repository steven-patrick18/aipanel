import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SAMPLE_SCRIPT =
  "Hi, my name is Sam. Today I'm going to read this short paragraph so the system can learn my voice. " +
  "I'll speak clearly, at my normal pace, with the kind of warmth I'd use on a real customer call. " +
  "When I'm done, the system will use this clip as a reference for everything I say going forward.";

const MAX_SECONDS = 60;
const MIN_SECONDS = 25;

interface VoiceRecorderProps {
  onComplete: (file: File) => void;
  onCancel: () => void;
}

/**
 * Browser-mic voice recording for the clone flow. Uses MediaRecorder with
 * audio/webm (Opus) → converts to a File the backend's TTS clone endpoint
 * accepts. Real WAV conversion would need ffmpeg.wasm or server-side
 * remux; for v1 we let the TTS service handle the format change.
 */
export function VoiceRecorder({ onComplete, onCancel }: VoiceRecorderProps) {
  const [permission, setPermission] = useState<"prompt" | "granted" | "denied">("prompt");
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const streamRef    = useRef<MediaStream | null>(null);
  const recorderRef  = useRef<MediaRecorder | null>(null);
  const chunksRef    = useRef<BlobPart[]>([]);
  const audioCtxRef  = useRef<AudioContext | null>(null);
  const rafRef       = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0);

  // Cleanup on unmount.
  useEffect(() => () => stopAll(), []);

  function stopAll() {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (audioCtxRef.current) audioCtxRef.current.close().catch(() => {});
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      try { recorderRef.current.stop(); } catch {}
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    audioCtxRef.current = null;
    rafRef.current = null;
  }

  async function startRecording() {
    setError(null);
    chunksRef.current = [];
    setSeconds(0);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 24000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      setPermission("granted");
    } catch (e: any) {
      setPermission("denied");
      setError(
        e?.name === "NotAllowedError"
          ? "Microphone permission denied. Enable it in your browser settings."
          : `Couldn't open mic: ${e?.message ?? e}`,
      );
      return;
    }
    streamRef.current = stream;

    // RMS meter via Web Audio API.
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    audioCtxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      // RMS over the buffer, normalised to 0..1.
      let sumSq = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sumSq += v * v;
      }
      setLevel(Math.min(1, Math.sqrt(sumSq / data.length) * 1.6));
      rafRef.current = requestAnimationFrame(tick);
    };
    tick();

    // Pick the best supported mime; Opus in webm is universal.
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : (MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "");
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    rec.ondataavailable = (ev) => {
      if (ev.data && ev.data.size) chunksRef.current.push(ev.data);
    };
    rec.onstop = () => {
      const blob = new Blob(chunksRef.current,
                            { type: mime || "audio/webm" });
      // Backend accepts wav/mp3/m4a; webm gets remuxed by the TTS server's
      // soundfile/librosa import. Filename hints to the operator what's inside.
      const ext = mime.includes("webm") ? "webm" : "ogg";
      const file = new File([blob], `voice-clone.${ext}`,
                            { type: blob.type });
      stopAll();
      setRecording(false);
      onComplete(file);
    };
    rec.start();
    recorderRef.current = rec;
    startedAtRef.current = performance.now();
    setRecording(true);

    // Timer + auto-stop at max.
    const timerId = setInterval(() => {
      const sec = (performance.now() - startedAtRef.current) / 1000;
      setSeconds(Math.floor(sec));
      if (sec >= MAX_SECONDS) {
        clearInterval(timerId);
        stop();
      }
    }, 200);
    (rec as any)._timerId = timerId;
  }

  function stop() {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") {
      const t = (rec as any)._timerId;
      if (t) clearInterval(t);
      try { rec.stop(); } catch {}
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-relaxed">
        <p className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">
          Read this aloud
        </p>
        <p className="text-slate-800">{SAMPLE_SCRIPT}</p>
      </div>

      {/* Audio meter */}
      <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className={cn(
            "h-full transition-[width] duration-75",
            level > 0.6 ? "bg-emerald-500" :
            level > 0.2 ? "bg-indigo-500"  : "bg-slate-300",
          )}
          style={{ width: `${Math.round(level * 100)}%` }}
        />
      </div>

      {/* Timer */}
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-mono text-slate-700">
          {seconds.toString().padStart(2, "0")}s / {MAX_SECONDS}s
        </span>
        {recording && seconds < MIN_SECONDS && (
          <span className="text-xs text-amber-600">
            Keep reading — at least {MIN_SECONDS}s for a quality clone.
          </span>
        )}
        {recording && seconds >= MIN_SECONDS && (
          <span className="text-xs text-emerald-600">Long enough — finish whenever you're ready.</span>
        )}
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}

      <div className="flex gap-2 justify-end pt-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        {!recording ? (
          <Button type="button" onClick={startRecording}>
            <Mic className="h-4 w-4" /> Start recording
          </Button>
        ) : (
          <Button
            type="button"
            variant={seconds >= MIN_SECONDS ? "success" : "destructive"}
            onClick={stop}
          >
            <Square className="h-4 w-4" /> Stop + save
          </Button>
        )}
      </div>
    </div>
  );
}
