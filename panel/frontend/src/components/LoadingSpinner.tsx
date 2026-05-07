import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center justify-center p-10 text-slate-400", className)}>
      <Loader2 className="h-5 w-5 animate-spin" />
    </div>
  );
}
