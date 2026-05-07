import { useState } from "react";
import { useParams } from "react-router-dom";
import { Search, Upload } from "lucide-react";
import {
  useKb, useKbDocuments, useSearchKb, useUploadKbDocument,
} from "@/api/hooks/useKb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fmtNumber, fmtRelative } from "@/lib/format";

export function KnowledgeBaseDetail() {
  const { id } = useParams<{ id: string }>();
  const kb = useKb(id);
  const { data: docs, isLoading: docsLoading } = useKbDocuments(id);
  const upload = useUploadKbDocument(id!);
  const search = useSearchKb(id!);
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("");

  if (kb.isLoading) return <LoadingSpinner />;

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) search.mutate({ query: query.trim(), limit: 8 });
  };
  const hits: any[] = (search.data as any)?.hits ?? [];

  return (
    <>
      <PageHeader
        title={kb.data?.name ?? "Knowledge base"}
        description={
          kb.data?.description ||
          "Documents in this collection. Ingest runs as a background job."
        }
        actions={
          <div className="flex gap-2 items-center">
            <input
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm"
            />
            <Button
              disabled={!file || upload.isPending}
              onClick={async () => {
                if (file) await upload.mutateAsync(file);
                setFile(null);
              }}
            >
              <Upload className="h-4 w-4" /> Upload
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          {docsLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (docs ?? []).length === 0 ? (
            <EmptyState
              icon={Upload}
              title="No documents yet"
              description="Upload a PDF, DOCX, or TXT to get started."
            />
          ) : (
            <Card className="p-0">
              <Table>
                <THead>
                  <TR>
                    <TH>Filename</TH>
                    <TH>Chunks</TH>
                    <TH>Status</TH>
                    <TH>Uploaded</TH>
                  </TR>
                </THead>
                <TBody>
                  {docs!.map((d) => (
                    <TR key={d.id}>
                      <TD className="font-medium">{d.filename}</TD>
                      <TD>{fmtNumber(d.chunk_count)}</TD>
                      <TD><StatusPill status={d.status} /></TD>
                      <TD className="text-slate-500">{fmtRelative(d.created_at)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </Card>
          )}
        </div>

        <Card>
          <CardHeader><CardTitle>Test retrieval</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={onSearch} className="flex gap-2 mb-3">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="What's the warranty?"
              />
              <Button type="submit" disabled={!query.trim() || search.isPending}>
                <Search className="h-4 w-4" />
              </Button>
            </form>
            {search.isPending ? (
              <Skeleton className="h-20 w-full" />
            ) : hits.length === 0 && search.isSuccess ? (
              <p className="text-sm text-slate-400">
                No matches. Upload a document and try again.
              </p>
            ) : hits.length > 0 ? (
              <ul className="space-y-2">
                {hits.map((h: any, i: number) => (
                  <li key={i}
                      className="rounded-md border border-slate-200 p-2 text-xs">
                    <p className="text-slate-700">{h.text ?? h.content}</p>
                    {typeof h.score === "number" && (
                      <p className="text-slate-400 mt-1">
                        score {h.score.toFixed(3)} · {h.source ?? "chunk"}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-slate-500">
                Type a question to preview what the AI agent would retrieve
                for it.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
