import { Link } from "react-router-dom";
import { PhoneCall } from "lucide-react";
import { useCalls } from "@/api/hooks/useCalls";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { fmtDate, fmtDuration } from "@/lib/format";

export function Calls() {
  const { data, isLoading } = useCalls({ limit: 100 });

  return (
    <>
      <PageHeader
        title="Calls"
        description="History of every call routed through aipanel."
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={PhoneCall}
          title="No calls yet"
          description="Calls will appear here once a deployment is running."
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Started</TH>
                <TH>Phone</TH>
                <TH>Outcome</TH>
                <TH>Dispo</TH>
                <TH>Duration</TH>
              </TR>
            </THead>
            <TBody>
              {data!.items.map((c) => (
                <TR key={c.id}>
                  <TD>
                    <Link to={`/calls/${c.id}`} className="font-medium hover:underline">
                      {fmtDate(c.started_at)}
                    </Link>
                  </TD>
                  <TD className="text-slate-600">{c.phone_number ?? "—"}</TD>
                  <TD className="text-slate-600">{c.outcome ?? "—"}</TD>
                  <TD className="text-slate-600">{c.dispo_code ?? "—"}</TD>
                  <TD className="text-slate-600">{fmtDuration(c.duration_sec)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
    </>
  );
}
