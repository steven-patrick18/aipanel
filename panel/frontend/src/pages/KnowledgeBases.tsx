import { useState } from "react";
import { Link } from "react-router-dom";
import { Database, Plus } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useCreateKb, useKbList } from "@/api/hooks/useKb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { kbCreateSchema } from "@/lib/validation";
import { canWrite } from "@/lib/permissions";
import { useAuth } from "@/auth/store";

export function KnowledgeBases() {
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading } = useKbList();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Knowledge bases"
        description="Document collections the LLM can search via the search_kb tool."
        actions={canWrite(role) && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> New KB</Button>
            </DialogTrigger>
            <NewKbDialog onDone={() => setOpen(false)} />
          </Dialog>
        )}
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={Database}
          title="No knowledge bases yet"
          description="Create one to feed product or policy docs into your agents."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data!.items.map((kb) => (
            <Link key={kb.id} to={`/knowledge-bases/${kb.id}`}>
              <Card className="p-4 hover:bg-slate-50 transition-colors">
                <p className="font-medium text-slate-900">{kb.name}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {kb.description || <span className="italic text-slate-400">No description</span>}
                </p>
                <p className="text-[11px] text-slate-400 mt-3">
                  Embedding model: {kb.embedding_model}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function NewKbDialog({ onDone }: { onDone: () => void }) {
  const form = useForm({
    resolver: zodResolver(kbCreateSchema),
    defaultValues: { name: "", description: "", embedding_model: "BAAI/bge-base-en-v1.5" },
  });
  const create = useCreateKb();

  const onSubmit = async (values: any) => {
    await create.mutateAsync(values);
    onDone();
  };

  return (
    <DialogContent>
      <DialogHeader><DialogTitle>New knowledge base</DialogTitle></DialogHeader>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="kb-name">Name</Label>
          <Input id="kb-name" {...form.register("name")} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kb-desc">Description</Label>
          <Textarea id="kb-desc" rows={3} {...form.register("description")} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kb-model">Embedding model</Label>
          <Input id="kb-model" {...form.register("embedding_model")} />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>Create</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
