import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Bot,
  Boxes,
  Database,
  Download,
  Headphones,
  LayoutDashboard,
  LogOut,
  PhoneCall,
  Server,
  ServerCog,
  Settings,
  Shield,
  Target,
  Users,
  Volume2,
} from "lucide-react";
import { useAuth } from "@/auth/store";
import { useLogout } from "@/api/hooks/useAuth";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { TooltipProvider } from "@/components/ui/tooltip";
import { canAdmin } from "@/lib/permissions";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

const NAV_PRIMARY: NavItem[] = [
  { to: "/",                  label: "Dashboard",        icon: LayoutDashboard },
  { to: "/agents",            label: "Agents",           icon: Bot },
  { to: "/campaigns",         label: "Campaigns",        icon: Target },
  { to: "/voices",            label: "Voices",           icon: Volume2 },
  { to: "/knowledge-bases",   label: "Knowledge bases",  icon: Database },
  { to: "/vicidial-servers",  label: "ViciDial servers", icon: ServerCog },
  { to: "/deployments",       label: "Deployments",      icon: Boxes },
  { to: "/calls",             label: "Calls",            icon: PhoneCall },
  { to: "/analytics",         label: "Analytics",        icon: BarChart3 },
];

const NAV_SYSTEM: NavItem[] = [
  { to: "/system/cluster",  label: "Cluster",   icon: Server },
  { to: "/system/health",   label: "Health",    icon: Activity },
  { to: "/system/settings", label: "Settings",  icon: Settings },
  { to: "/system/users",    label: "Users",     icon: Users, adminOnly: true },
  { to: "/system/audit",    label: "Audit log", icon: Shield, adminOnly: true },
  { to: "/system/updates",  label: "Updates",   icon: Download, adminOnly: true },
];

function NavGroup({ title, items, role }: { title: string; items: NavItem[]; role: any }) {
  return (
    <div>
      <p className="px-3 mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {title}
      </p>
      <ul className="space-y-0.5">
        {items
          .filter((it) => !it.adminOnly || canAdmin(role))
          .map((it) => (
            <li key={it.to}>
              <NavLink
                to={it.to}
                end={it.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-indigo-50 text-indigo-700 font-medium"
                      : "text-slate-700 hover:bg-slate-100",
                  )
                }
              >
                <it.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{it.label}</span>
              </NavLink>
            </li>
          ))}
      </ul>
    </div>
  );
}

function Topbar() {
  const user = useAuth((s) => s.user);
  const logout = useLogout();
  const location = useLocation();

  // Trim a route to its first segment for a Breadcrumb-ish title.
  const seg = location.pathname.split("/")[1] || "dashboard";
  const title = seg
    .replace(/-/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());

  return (
    <header className="h-16 border-b border-slate-200 bg-white px-6 flex items-center justify-between">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="gap-2">
            <span className="h-7 w-7 rounded-full bg-indigo-100 text-indigo-700 grid place-items-center text-xs font-semibold">
              {user?.email[0]?.toUpperCase() ?? "?"}
            </span>
            <span className="text-sm">{user?.email}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel>{user?.role}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => logout.mutate()}>
            <LogOut className="h-4 w-4 mr-2" /> Log out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}

export function AppLayout() {
  const role = useAuth((s) => s.user?.role);
  return (
    <TooltipProvider>
      <div className="h-full grid grid-cols-[240px_1fr] grid-rows-1 bg-slate-50">
        <aside className="row-span-1 h-full border-r border-slate-200 bg-white p-4 flex flex-col">
          <Link to="/" className="flex items-center gap-2 mb-6 px-2">
            <span className="h-8 w-8 rounded-md bg-indigo-600 grid place-items-center text-white font-bold text-sm">
              ai
            </span>
            <span className="font-semibold text-slate-900">aipanel</span>
          </Link>

          <nav className="flex-1 overflow-y-auto space-y-6">
            <NavGroup title="Workspace" items={NAV_PRIMARY} role={role} />
            <NavGroup title="System"    items={NAV_SYSTEM}  role={role} />
          </nav>

          <div className="text-[11px] text-slate-400 px-3 pt-3">
            <Headphones className="h-3 w-3 inline-block mr-1" />
            v0.8.0
          </div>
        </aside>

        <div className="flex flex-col min-w-0">
          <Topbar />
          <main className="flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
