import { useState } from "react";
import { Shield } from "lucide-react";
import { useAuth } from "@/auth/store";
import { useAudit } from "@/api/hooks/useUsers";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";

const PAGE = 100;

export function Audit() {
  const me = useAuth((s) => s.user);
  const tenantId = me?.tenant_id;
  const [prefix, setPrefix] = useState("");
  const [offset, setOffset] = useState(0);
  const { data: rows, isLoading } = useAudit(tenantId, {
    limit: PAGE,
    offset,
    action_prefix: prefix || undefined,
  });

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every mutation made by every user, newest first. Auto-refreshes every 15 s."
      />

      <Card className="mb-4 p-4">
        <div className="flex items-end gap-3">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="al-prefix">Filter by action prefix</Label>
            <Input
              id="al-prefix"
              placeholder="agent. / deployment. / user. / voice. …"
              value={prefix}
              onChange={(e) => { setOffset(0); setPrefix(e.target.value); }}
            />
          </div>
          <div className="flex gap-2">
            <Button
              type="button" variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              ← Newer
            </Button>
            <Button
              type="button" variant="outline"
              disabled={!rows || rows.length < PAGE}
              onClick={() => setOffset(offset + PAGE)}
            >
              Older →
            </Button>
          </div>
        </div>
      </Card>

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          icon={Shield}
          title="No audit entries"
          description={prefix
            ? `Nothing matched "${prefix}" in this window.`
            : "Once people start making changes they'll show up here."}
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Action</TH>
                <TH>Target</TH>
                <TH>Payload</TH>
              </TR>
            </THead>
            <TBody>
              {(rows ?? []).map((r) => (
                <TR key={r.id}>
                  <TD className="whitespace-nowrap text-slate-500 text-sm">
                    {fmtRelative(r.ts)}
                  </TD>
                  <TD className="font-mono text-xs">{r.action}</TD>
                  <TD className="text-xs text-slate-600">
                    {r.target_type ?? "—"}
                    {r.target_id && (
                      <span className="ml-1 text-slate-400">
                        {r.target_id.slice(0, 8)}…
                      </span>
                    )}
                  </TD>
                  <TD className="max-w-xl truncate text-xs text-slate-500">
                    {Object.keys(r.payload).length === 0
                      ? "—"
                      : JSON.stringify(r.payload)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}

      <p className="mt-3 text-xs text-slate-500">
        Showing entries {offset + 1}–{offset + (rows?.length ?? 0)} (page size {PAGE}).
      </p>
    </>
  );
}
