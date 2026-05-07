import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./store";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.accessToken);
  const location = useLocation();

  if (!token) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}
