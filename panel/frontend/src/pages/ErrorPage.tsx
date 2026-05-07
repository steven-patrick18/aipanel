import { Link, useRouteError } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ErrorPage() {
  const err = useRouteError() as any;
  const message = err?.statusText || err?.message || "Something went wrong.";
  return (
    <div className="min-h-full flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div className="mx-auto mb-3 h-12 w-12 grid place-items-center rounded-full bg-rose-50 text-rose-500">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <h1 className="text-lg font-semibold text-slate-900">Unexpected error</h1>
        <p className="mt-1 text-sm text-slate-500">{message}</p>
        <Button asChild className="mt-4">
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    </div>
  );
}
