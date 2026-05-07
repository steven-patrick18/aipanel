import { Outlet } from "react-router-dom";

export function AuthLayout() {
  return (
    <div className="min-h-full flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-indigo-50 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto h-12 w-12 rounded-lg bg-indigo-600 grid place-items-center text-white font-bold text-lg">
            ai
          </div>
          <h1 className="mt-3 text-xl font-semibold text-slate-900">aipanel</h1>
          <p className="text-sm text-slate-500">Voice agent control plane</p>
        </div>
        <Outlet />
      </div>
    </div>
  );
}
