import { createBrowserRouter, Navigate } from "react-router-dom";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { AppLayout } from "@/layouts/AppLayout";
import { AuthLayout } from "@/layouts/AuthLayout";
import { ErrorPage } from "@/pages/ErrorPage";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { AgentsList } from "@/pages/AgentsList";
import { AgentDetail } from "@/pages/AgentDetail";
import { Voices } from "@/pages/Voices";
import { Campaigns } from "@/pages/Campaigns";
import { CampaignDetail } from "@/pages/CampaignDetail";
import { KnowledgeBases } from "@/pages/KnowledgeBases";
import { KnowledgeBaseDetail } from "@/pages/KnowledgeBaseDetail";
import { ViciDialServers } from "@/pages/ViciDialServers";
import { Deployments } from "@/pages/Deployments";
import { DeploymentDetail } from "@/pages/DeploymentDetail";
import { Calls } from "@/pages/Calls";
import { CallDetail } from "@/pages/CallDetail";
import { Analytics } from "@/pages/Analytics";
import { Cluster } from "@/pages/system/Cluster";
import { Health } from "@/pages/system/Health";
import { Settings } from "@/pages/system/Settings";
import { Users } from "@/pages/system/Users";
import { Audit } from "@/pages/system/Audit";
import { Updates } from "@/pages/system/Updates";

export const router = createBrowserRouter([
  {
    element: <AuthLayout />,
    errorElement: <ErrorPage />,
    children: [
      { path: "/login", element: <Login /> },
    ],
  },
  {
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    errorElement: <ErrorPage />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/agents", element: <AgentsList /> },
      { path: "/agents/:id", element: <AgentDetail /> },
      { path: "/campaigns", element: <Campaigns /> },
      { path: "/campaigns/:id", element: <CampaignDetail /> },
      { path: "/voices", element: <Voices /> },
      { path: "/knowledge-bases", element: <KnowledgeBases /> },
      { path: "/knowledge-bases/:id", element: <KnowledgeBaseDetail /> },
      { path: "/vicidial-servers", element: <ViciDialServers /> },
      { path: "/deployments", element: <Deployments /> },
      { path: "/deployments/:id", element: <DeploymentDetail /> },
      { path: "/calls", element: <Calls /> },
      { path: "/calls/:id", element: <CallDetail /> },
      { path: "/analytics", element: <Analytics /> },
      { path: "/system/cluster", element: <Cluster /> },
      { path: "/system/health", element: <Health /> },
      { path: "/system/settings", element: <Settings /> },
      { path: "/system/users", element: <Users /> },
      { path: "/system/audit", element: <Audit /> },
      { path: "/system/updates", element: <Updates /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
