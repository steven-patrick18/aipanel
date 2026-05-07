export type Role = "admin" | "operator" | "viewer";

export const canWrite = (role: Role | null | undefined): boolean =>
  role === "admin" || role === "operator";

export const canAdmin = (role: Role | null | undefined): boolean =>
  role === "admin";
