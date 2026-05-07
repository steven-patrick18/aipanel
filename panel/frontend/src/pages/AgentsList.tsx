import { Link, useNavigate } from "react-router-dom";
import { Bot, Plus } from "lucide-react";
import { useState } from "react";
import { useAgents, useArchiveAgent, useCreateAgent, useDuplicateAgent } from "@/api/hooks/useAgents";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtRelative } from "@/lib/format";
import { canWrite } from "@/lib/permissions";
import { useAuth } from "@/auth/store";

export function AgentsList() {
  const role = useAuth((s) => s.user?.role);
  const nav = useNavigate();
  const [filter, setFilter] = useState("");
  const { data, isLoading } = useAgents({ name_contains: filter || undefined });
  const create = useCreateAgent();
  const dup = useDuplicateAgent();
  const archive = useArchiveAgent();

  const handleNew = async () => {
    const a = await create.mutateAsync({
      name: "Untitled agent",
      language: "en",
      persona: {
        name: "Untitled", age_range: "30-40", gender: "neutral",
        accent: "neutral US", backstory: "An outreach specialist.",
      },
      script: { opening_variants: ["Hi there."], sections: [], closing: "Thanks.", objections: [] },
      scenario_tree: { rules: [] },
    });
    nav(`/agents/${a.id}`);
  };

  return (
    <>
      <PageHeader
        title="Agents"
        description="Personas, scripts, and call-handling rules for your voice AI."
        actions={
          canWrite(role) && (
            <Button onClick={handleNew} disabled={create.isPending}>
              <Plus className="h-4 w-4" /> New agent
            </Button>
          )
        }
      />

      <Card className="p-3 mb-4">
        <Input
          placeholder="Search by name…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </Card>

      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No agents yet"
          description="Create your first AI agent to start handling calls."
          action={canWrite(role) && (
            <Button onClick={handleNew} disabled={create.isPending}>
              <Plus className="h-4 w-4" /> Create agent
            </Button>
          )}
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Status</TH>
                <TH>Language</TH>
                <TH>Updated</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {data!.items.map((a) => (
                <TR key={a.id}>
                  <TD>
                    <Link
                      to={`/agents/${a.id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {a.name}
                    </Link>
                  </TD>
                  <TD><StatusPill status={a.status} /></TD>
                  <TD className="text-slate-600">{a.language}</TD>
                  <TD className="text-slate-500">{fmtRelative(a.updated_at)}</TD>
                  <TD className="text-right">
                    {canWrite(role) && (
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm" variant="ghost"
                          onClick={() => dup.mutate(a.id)}
                        >
                          Duplicate
                        </Button>
                        <Button
                          size="sm" variant="ghost"
                          onClick={() => {
                            if (confirm(`Archive "${a.name}"?`)) {
                              archive.mutate(a.id);
                            }
                          }}
                        >
                          Archive
                        </Button>
                      </div>
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
