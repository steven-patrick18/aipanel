import { useState } from "react";
import { Plus, ServerCog } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useCreateVicidialServer,
  useTestVicidialConnection,
  useVicidialServers,
} from "@/api/hooks/useVicidialServers";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { vicidialServerSchema } from "@/lib/validation";
import { canWrite } from "@/lib/permissions";
import { useAuth } from "@/auth/store";

export function ViciDialServers() {
  const role = useAuth((s) => s.user?.role);
  const { data, isLoading } = useVicidialServers();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="ViciDial servers"
        description="Connections used by Session Manager to log in agents."
        actions={canWrite(role) && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> Add server</Button>
            </DialogTrigger>
            <NewServerDialog onDone={() => setOpen(false)} />
          </Dialog>
        )}
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState
          icon={ServerCog}
          title="No ViciDial servers configured"
          description="Add your dialler's web admin URL + AMI credentials."
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Web URL</TH>
                <TH>Asterisk host</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {data!.items.map((s) => (
                <ServerRow key={s.id} server={s} />
              ))}
            </TBody>
          </Table>
        </Card>
      )}
    </>
  );
}

function ServerRow({ server }: { server: any }) {
  const test = useTestVicidialConnection(server.id);
  return (
    <TR>
      <TD className="font-medium">{server.name}</TD>
      <TD className="text-slate-600 break-all">{server.web_url}</TD>
      <TD className="text-slate-600">{server.asterisk_host}:{server.asterisk_port}</TD>
      <TD className="text-right">
        <Button
          size="sm" variant="ghost"
          onClick={() => test.mutate()}
          disabled={test.isPending}
        >
          Test connection
        </Button>
      </TD>
    </TR>
  );
}

function NewServerDialog({ onDone }: { onDone: () => void }) {
  const create = useCreateVicidialServer();
  const form = useForm({
    resolver: zodResolver(vicidialServerSchema),
    defaultValues: {
      name: "", asterisk_host: "", asterisk_port: 5038,
      web_url: "", ami_user: "", ami_pass: "",
      web_user_admin: "", web_pass: "",
    },
  });

  const onSubmit = async (values: any) => {
    await create.mutateAsync(values);
    onDone();
  };

  return (
    <DialogContent>
      <DialogHeader><DialogTitle>Register a ViciDial server</DialogTitle></DialogHeader>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
        {([
          ["Display name",  "name"],
          ["Web URL",       "web_url",       "https://vici.example.com"],
          ["Asterisk host", "asterisk_host", "vici.example.com"],
          ["Asterisk port", "asterisk_port"],
          ["AMI user",      "ami_user"],
          ["AMI password",  "ami_pass",      "", "password"],
          ["Admin user",    "web_user_admin"],
          ["Admin password","web_pass",      "", "password"],
        ] as const).map(([label, field, ph, type]) => (
          <div key={field} className="space-y-1">
            <Label>{label}</Label>
            <Input
              type={(type as string) || "text"}
              placeholder={(ph as string) || ""}
              {...form.register(field as any, { valueAsNumber: field === "asterisk_port" })}
            />
          </div>
        ))}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>Save</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
