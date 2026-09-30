export class ApiError extends Error {}

export async function api<T = any>(path: string, method = "GET", body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`/api${path}`, { method, headers: { "Content-Type": "application/json" }, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError("We can't reach the Confiance service. Please make sure it is running, then try again.");
  }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    const d = j.detail;
    throw new ApiError(typeof d === "string" ? d : "Something went wrong. Please try again.");
  }
  return r.json();
}
