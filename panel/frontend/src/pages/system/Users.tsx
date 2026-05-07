import { useState } from "react";
import { useForm } from "react-hook-form";
import { Plus, Trash2, Users as UsersIcon } from "lucide-react";
import { useAuth } from "@/auth/store";
import {
  useDeleteUser,
  useInviteUser,
  useUpdateUserRole,
  useUsers,
} from "@/api/hooks/useUsers";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import type { Role } from "@/lib/types";

export function Users() {
  const me = useAuth((s) => s.user);
  const tenantId = me?.tenant_id;
  const isAdmin = me?.role === "admin";
  const { data: users, isLoading } = useUsers(tenantId);
  const updateRole = useUpdateUserRole(tenantId ?? "");
  const del = useDeleteUser(tenantId ?? "");
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Users"
        description="People who can sign in to this tenant. Admins manage roles + access."
        actions={isAdmin && tenantId && (
          <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4" /> Invite user</Button>
            </DialogTrigger>
            <InviteDialog tenantId={tenantId} onDone={() => setInviteOpen(false)} />
          </Dialog>
        )}
      />

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (users ?? []).length === 0 ? (
        <EmptyState
          icon={UsersIcon}
          title="No users yet"
          description="Invite the first teammate to give them access."
        />
      ) : (
        <Card className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Email</TH>
                <TH>Role</TH>
                <TH>Joined</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {(users ?? []).map((u) => {
                const isMe = u.id === me?.id;
                return (
                  <TR key={u.id}>
                    <TD className="font-medium">
                      {u.email}
                      {isMe && (
                        <span className="ml-2 text-xs text-slate-500">(you)</span>
                      )}
                    </TD>
                    <TD>
                      {isAdmin ? (
                        <Select
                          value={u.role}
                          onValueChange={(role) =>
                            updateRole.mutate({ userId: u.id, role: role as Role })
                          }
                          disabled={isMe && u.role === "admin"}
                        >
                          <SelectTrigger className="h-8 w-[140px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="admin">admin</SelectItem>
                            <SelectItem value="operator">operator</SelectItem>
                            <SelectItem value="viewer">viewer</SelectItem>
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className="text-sm text-slate-700">{u.role}</span>
                      )}
                    </TD>
                    <TD className="text-slate-500 text-sm">
                      {fmtRelative(u.created_at)}
                    </TD>
                    <TD className="text-right">
                      {isAdmin && !isMe && (
                        <Button
                          size="sm" variant="ghost"
                          onClick={() => {
                            if (confirm(`Remove ${u.email}? They lose access immediately.`)) {
                              del.mutate(u.id);
                            }
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" /> Remove
                        </Button>
                      )}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </Card>
      )}

      {!isAdmin && (
        <p className="mt-3 text-xs text-slate-500">
          Only admins can invite or remove users.
        </p>
      )}
    </>
  );
}

function InviteDialog({
  tenantId, onDone,
}: { tenantId: string; onDone: () => void }) {
  const invite = useInviteUser(tenantId);
  const form = useForm<{ email: string; password: string; role: Role }>({
    defaultValues: { email: "", password: "", role: "viewer" },
  });

  const submit = async (vals: { email: string; password: string; role: Role }) => {
    if (vals.password.length < 8) {
      alert("Password must be at least 8 characters.");
      return;
    }
    await invite.mutateAsync(vals);
    onDone();
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Invite a user</DialogTitle>
        <DialogDescription>
          They sign in with the email and the temporary password you set.
          Tell them to change it after first login.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={form.handleSubmit(submit)} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="iu-email">Email</Label>
          <Input id="iu-email" type="email" autoComplete="off"
                 {...form.register("email", { required: true })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="iu-pass">Temporary password (≥ 8 chars)</Label>
          <Input id="iu-pass" type="text" autoComplete="off"
                 {...form.register("password", { required: true })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="iu-role">Role</Label>
          <Select
            value={form.watch("role")}
            onValueChange={(v) => form.setValue("role", v as Role)}
          >
            <SelectTrigger id="iu-role"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="admin">admin · full control</SelectItem>
              <SelectItem value="operator">operator · CRUD + run calls</SelectItem>
              <SelectItem value="viewer">viewer · read-only</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
          <Button type="submit" disabled={invite.isPending}>Invite</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
