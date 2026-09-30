import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch with stale-while-revalidate: the previous data stays on screen while a refresh is in flight, so pages
 *  never flash back to "Loading…" or jump around. `poll` (ms) re-fetches on an interval. */
export function useApi<T = any>(path: string | null, opts: { poll?: number; deps?: unknown[] } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!!path);
  const cur = useRef(path);
  cur.current = path;
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (cur.current === path) { setData(d); setError(""); }
    } catch (e: any) { if (cur.current === path) setError(e.message || "Something went wrong."); }
    finally { if (cur.current === path) setLoading(false); }
  }, [path]);
  useEffect(() => { setLoading(!!path); if (path) load(); else { setData(null); } }, [path, ...(opts.deps ?? [])]);
  useEffect(() => { if (!opts.poll || !path) return; const t = setInterval(load, opts.poll); return () => clearInterval(t); }, [opts.poll, path, load]);
  return { data, error, loading, reload: load, setData };
}

let taskSeq = 0;
/** Runs one action at a time. `key` names the running task so the server can report live activity for it (pass it to
 *  api(..., { task: key }) and show <TaskFeed task={key} on={busy} />). */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState<string | null>(null);
  const run = async <T,>(f: (task: string) => Promise<T>): Promise<T | undefined> => {
    const k = `ui-${Date.now().toString(36)}-${++taskSeq}`;
    setBusy(true); setError(""); setKey(k);
    try { return await f(k); } catch (e: any) { setError(e.message || "Something went wrong."); } finally { setBusy(false); }
  };
  return { busy, error, key, run, clear: () => setError("") };
}

export function usePoll(fn: () => void, ms: number, on = true) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => { if (!on) return; ref.current(); const t = setInterval(() => ref.current(), ms); return () => clearInterval(t); }, [on, ms]);
}

export function useLocal<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => { try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : initial; } catch { return initial; } });
  return [v, (n: T) => { setV(n); try { localStorage.setItem(key, JSON.stringify(n)); } catch { /* private mode */ } }];
}
