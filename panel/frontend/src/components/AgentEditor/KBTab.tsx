import { Controller, useFormContext } from "react-hook-form";
import { Database } from "lucide-react";
import { useKbList } from "@/api/hooks/useKb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { AgentCreateInput } from "@/lib/validation";

export function KBTab() {
  const { control } = useFormContext<AgentCreateInput>();
  const { data, isLoading } = useKbList();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Knowledge base</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Attach a knowledge base</Label>
            {isLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Controller
                name="kb_collection_id"
                control={control}
                render={({ field }) => (
                  <Select
                    value={field.value ?? ""}
                    onValueChange={(v) => field.onChange(v || null)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="No KB attached" />
                    </SelectTrigger>
                    <SelectContent>
                      {(data?.items ?? []).length === 0 && (
                        <div className="p-2 text-xs text-slate-500">
                          No KBs yet. Create one on the Knowledge Bases page.
                        </div>
                      )}
                      {(data?.items ?? []).map((kb) => (
                        <SelectItem key={kb.id} value={kb.id}>
                          {kb.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            )}
            <p className="text-xs text-slate-500">
              When a KB is attached, the LLM gets a <code>search_kb</code> tool to
              answer factual questions.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Test query</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-slate-500 flex items-center gap-2">
            <Database className="h-4 w-4 text-slate-400" />
            Ingest pipeline (PDF/DOCX → chunks → embeddings) lands with the
            embed-server. Search currently returns no hits.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
