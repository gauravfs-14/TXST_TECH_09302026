import { useEffect, useState } from "react";
import { api } from "../api";
import { Banner, Button, Choice, Field, Icon, useAction } from "../ui";

type Preset = "gemini" | "ollama" | "openai" | "other";
// rpm/conc are gentle defaults for how fast Confiance may call the service (rpm 0 = no limit of our own).
const PRESETS: Record<Preset, { title: string; text: string; url: string; key: boolean; rpm: number; conc: number; badge?: string }> = {
  gemini: { title: "Google Gemini", text: "A generous free allowance and good at structured answers. Google may use free-tier prompts to improve its products, so try it with public websites, not confidential ones.", url: "https://generativelanguage.googleapis.com/v1beta/openai/", key: true, rpm: 15, conc: 4, badge: "Best free option" },
  ollama: { title: "Ollama on this computer", text: "Free. Runs AI on your own machine, so nothing is sent anywhere.", url: "http://localhost:11434/v1", key: false, rpm: 0, conc: 2 },
  openai: { title: "OpenAI (ChatGPT)", text: "The company behind ChatGPT. Needs an account and a key.", url: "https://api.openai.com/v1", key: true, rpm: 0, conc: 4 },
  other: { title: "Another provider", text: "Any service that works like OpenAI: OpenRouter, Groq, LM Studio and others.", url: "", key: true, rpm: 0, conc: 4 },
};
const presetOf = (url: string): Preset => (url.includes("googleapis.com") ? "gemini" : /localhost|127\.0\.0\.1/.test(url) ? "ollama" : url.includes("api.openai.com") ? "openai" : "other");

type Result = { ok: boolean; message: string; tools?: boolean };

function ModelPick({ models, value, onChange, optional }: { models: string[]; value: string; onChange: (v: string) => void; optional?: boolean }) {
  if (models.length === 0) return <input type="text" value={value} onChange={e => onChange(e.target.value)} placeholder={optional ? "Optional. Press “Find my models” or type a name" : "Press “Find my models”, or type a model name"} />;
  return (<select value={value} onChange={e => onChange(e.target.value)} aria-label="Model">
    {optional && <option value="">Same as the main model</option>}
    {models.map(m => <option key={m} value={m}>{m}</option>)}
    {value && !models.includes(value) && <option value={value}>{value}</option>}
  </select>);
}

function Verdict({ r }: { r: Result | null }) {
  if (!r) return null;
  return <Banner kind={r.ok && r.tools !== false ? "info" : r.ok ? "warn" : "bad"}><b>{r.ok && r.tools !== false ? "✓ " : ""}{r.message}</b></Banner>;
}

export function AiModelForm({ onDone, cfg }: { onDone?: () => void; cfg: any }) {
  const configured = !!cfg?.llm_model;
  const [preset, setPreset] = useState<Preset | null>(configured ? presetOf(cfg.llm_base_url) : null);
  const [url, setUrl] = useState(configured ? cfg.llm_base_url : "");
  const [key, setKey] = useState("");
  const [model, setModel] = useState(cfg?.llm_model ?? "");
  const [fast, setFast] = useState(cfg?.llm_worker_model ?? "");
  const [models, setModels] = useState<string[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [findErr, setFindErr] = useState("");
  const find = useAction(), save = useAction();

  const choose = (p: Preset) => { setPreset(p); setUrl(p === "other" ? (preset === "other" ? url : "") : PRESETS[p].url); setModels([]); setResult(null); setFindErr(""); };
  const findModels = () => find.run(async () => {
    setFindErr("");
    const r = await api("/setup/models", "POST", { base_url: url, api_key: key });
    if (r.error) { setFindErr(r.error); setModels([]); return; }
    setModels(r.models);
    if (r.suggested?.main || r.suggested?.fast) {  // e.g. Gemini: newest Flash for hard jobs, Flash-Lite for the many small ones
      if (!model) setModel(r.suggested.main ?? r.suggested.fast);
      if (!fast) setFast(r.suggested.fast ?? "");
    } else if (!model && r.models.length) setModel(r.models[0]);
    if (!r.models.length) setFindErr("Connected, but no models were found. If it's Ollama, download one first.");
  });
  const saveTest = () => save.run(async () => {
    setResult(null);
    const pr = PRESETS[preset!];
    await api("/setup/config", "PUT", { llm_base_url: url, llm_model: model, llm_worker_model: fast === model ? "" : fast,
      llm_rpm: pr.rpm, llm_max_concurrency: pr.conc, ...(key ? { llm_api_key: key } : {}) });
    const r: Result = await api("/setup/test-llm", "POST");
    setResult(r);
    if (r.ok) { setKey(""); onDone?.(); }
  });
  const needsKey = preset ? PRESETS[preset].key : false;
  const ready = !!preset && !!url.trim() && !!model.trim();

  return (<div>
    <div className="stack">{(Object.keys(PRESETS) as Preset[]).map(p => (
      <Choice key={p} icon={p === "ollama" ? "box" : p === "gemini" ? "spark" : "globe"} title={PRESETS[p].title} text={PRESETS[p].text} badge={PRESETS[p].badge} on={preset === p} onClick={() => choose(p)} />))}</div>

    {preset && (<div style={{ marginTop: "1.25rem" }}>
      {preset === "gemini" && <p className="muted small">Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a>. Free limits are per Google project and are shown in your AI Studio dashboard. Confiance paces itself and backs off automatically.</p>}
      {preset === "ollama" && <p className="muted small">Ollama is a free program from <a href="https://ollama.com" target="_blank" rel="noreferrer">ollama.com</a>. Make sure it is open and you have downloaded at least one model.</p>}
      {preset === "other" && <Field label="Web address of the service" hint="It usually ends in /v1, for example https://openrouter.ai/api/v1">
        <input type="text" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…/v1" /></Field>}
      {needsKey && <Field label="Your key" hint={cfg?.has_llm_key && !key ? "A key is already saved. Leave this empty to keep it." : preset === "gemini" ? "Create one at aistudio.google.com/apikey" : preset === "openai" ? "Create one at platform.openai.com/api-keys" : "From your provider's account page."}>
        <input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={cfg?.has_llm_key ? "••••••••  (saved)" : "Paste your key here"} /></Field>}

      <Field label="Main model" hint="Does the hard thinking, but is used sparingly. Needs to be able to use tools.">
        <ModelPick models={models} value={model} onChange={setModel} />
      </Field>
      <Field label="Fast model (optional)" hint="Handles the many small jobs, like pretending to be customers. A lighter model here saves your free allowance. Leave empty to use the main model for everything.">
        <div className="row"><div className="grow"><ModelPick models={models} value={fast} onChange={setFast} optional /></div>
          <Button kind="quiet" busy={find.busy} disabled={!url.trim() || (needsKey && !key && !cfg?.has_llm_key)} onClick={findModels}><Icon n="search" size={16} />Find my models</Button></div>
      </Field>
      {findErr && <Banner kind="bad">{findErr}</Banner>}
      {save.error && <Banner kind="bad">{save.error}</Banner>}
      <Verdict r={result} />
      <div className="row"><Button busy={save.busy} disabled={!ready} onClick={saveTest}>{save.busy ? "Testing (the first time can take a minute)…" : "Save and test"}</Button>
        <span className="muted small"><Icon n="shield" size={14} /> Kept on this computer. Never shown again.</span></div>
    </div>)}
  </div>);
}

export function SearchForm({ cfg, onDone }: { cfg: any; onDone?: () => void }) {
  const [choice, setChoice] = useState<"duckduckgo" | "tavily">(cfg?.search_provider === "tavily" ? "tavily" : "duckduckgo");
  const [key, setKey] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const { busy, error, run } = useAction();
  const go = () => run(async () => {
    setResult(null);
    await api("/setup/config", "PUT", { search_provider: choice, ...(choice === "tavily" && key ? { search_api_key: key } : {}) });
    const r: Result = await api("/setup/test-search", "POST");
    setResult(r); if (r.ok) { setKey(""); onDone?.(); }
  });
  return (<div>
    <div className="stack">
      <Choice icon="search" title="Free search" text="Uses DuckDuckGo. No account needed. Great for trying things out." badge="Recommended to start" on={choice === "duckduckgo"} onClick={() => setChoice("duckduckgo")} />
      <Choice icon="key" title="Tavily" text="Better, steadier results for real projects. Needs a free account." on={choice === "tavily"} onClick={() => setChoice("tavily")} />
    </div>
    {choice === "tavily" && <div style={{ marginTop: "1rem" }}><Field label="Tavily key" hint="Sign up at app.tavily.com. Your key is on the first page.">
      <input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={cfg?.has_search_key ? "••••••••  (saved)" : "Paste your key here"} /></Field></div>}
    {error && <Banner kind="bad">{error}</Banner>}
    <Verdict r={result} />
    <div style={{ marginTop: "1rem" }}><Button kind="quiet" busy={busy} disabled={choice === "tavily" && !key && !cfg?.has_search_key} onClick={go}>Save and test search</Button></div>
  </div>);
}

export function Accounts({ onSaved }: { onSaved?: () => void }) {
  const [cfg, setCfg] = useState<any>(null);
  const load = () => api("/setup/config").then(setCfg);
  useEffect(() => { load(); }, []);
  if (!cfg) return <p className="muted">Loading…</p>;
  return (<div>
    <div className="card flat"><h3>1. AI model</h3><AiModelForm cfg={cfg} onDone={() => { load(); onSaved?.(); }} /></div>
    <div className="card flat"><h3>2. Looking things up on the web</h3><SearchForm cfg={cfg} onDone={load} /></div>
  </div>);
}
