import { useSafeConfig } from "@/api/hooks/useSystem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";

export function Settings() {
  const { data, isLoading } = useSafeConfig();

  return (
    <>
      <PageHeader
        title="Settings"
        description="Read-only view of /etc/aipanel/aipanel.conf (secrets redacted)."
      />
      <Card>
        <CardHeader><CardTitle>Configuration</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : data ? (
            <dl className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <Row label="Public URL"  value={data.panel_public_url} />
              <Row label="SIP port"    value={String(data.sip_listen_port)} />
              <Row label="LLM model"   value={data.llm_model} />
              <Row label="STT model"   value={data.stt_model} />
              <Row label="TTS backend" value={data.tts_backend} />
            </dl>
          ) : (
            <p className="text-sm text-slate-400">Could not load config.</p>
          )}
          <p className="text-xs text-slate-500 mt-4">
            To edit, modify <code>/etc/aipanel/aipanel.conf</code> on the server and
            restart the affected systemd unit.
          </p>
        </CardContent>
      </Card>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-slate-100 pb-2">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-slate-900">{value}</dd>
    </div>
  );
}
