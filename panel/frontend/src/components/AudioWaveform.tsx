import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * Synthetic waveform visualisation — draws a sliding window of randomised
 * bars to indicate "audio is flowing". A real implementation would consume
 * the inbound RTP stream, but the SIP layer doesn't expose audio to the
 * panel today. Wire this to a Redis pubsub of frame-level RMS later.
 */
export function AudioWaveform({
  active = true,
  className,
}: {
  active?: boolean;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    const bars = 64;
    const heights = new Array<number>(bars).fill(0.05);

    const draw = () => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const barW = w / bars;

      // Shift left, generate one new sample on the right.
      for (let i = 0; i < bars - 1; i++) heights[i] = heights[i + 1];
      heights[bars - 1] = active ? 0.15 + Math.random() * 0.85 : 0.05;

      for (let i = 0; i < bars; i++) {
        const barH = heights[i] * h * 0.9;
        const x = i * barW + 0.5;
        const y = (h - barH) / 2;
        ctx.fillStyle = active
          ? `rgba(79, 70, 229, ${0.45 + heights[i] * 0.55})`
          : "rgba(148, 163, 184, 0.4)";
        ctx.fillRect(x, y, barW - 1, barH);
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active]);

  return (
    <canvas
      ref={canvasRef}
      width={480}
      height={72}
      className={cn("w-full h-[72px] rounded-md bg-slate-50", className)}
    />
  );
}
