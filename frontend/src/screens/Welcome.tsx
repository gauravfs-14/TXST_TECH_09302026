import { useEffect, useState } from "react";
import { api } from "../api";
import { Icon } from "../ui";
import { AiModelForm, SearchForm } from "./Accounts";

export function Welcome({ status, onReady }: { status: Record<string, boolean>; onReady: () => void }) {
  const [cfg, setCfg] = useState<any>(null);
  const load = () => api("/setup/config").then(setCfg);
  useEffect(() => { load(); }, []);
  return (<div className="narrow">
    <div className="center" style={{ margin: "1rem 0 2rem" }}>
      <span style={{ color: "var(--primary)" }}><Icon n="leaf" size={44} /></span>
      <h1 style={{ marginTop: ".5rem" }}>Welcome to Confiance</h1>
      <p className="muted" style={{ fontSize: "1.1rem" }}>People now ask AI assistants like ChatGPT for advice instead of searching Google.
        Confiance helps those assistants find your business and describe it accurately.</p>
    </div>
    <div className="card">
      <h2>First, connect an AI model</h2>
      <p className="muted">Confiance needs an AI to do its thinking. You can use one that runs free on your own computer, or an online service. You only do this once.</p>
      {cfg && <AiModelForm cfg={cfg} onDone={() => { load(); onReady(); }} />}
    </div>
    <div className="card">
      <h2>Then, how should we look things up?</h2>
      <p className="muted">The free option works without any account. You can change this later in Settings.</p>
      {cfg && <SearchForm cfg={cfg} onDone={() => { load(); onReady(); }} />}
    </div>
    {status.llm && status.search && <div className="center"><button className="btn primary big" onClick={onReady}>Continue <Icon n="arrow" /></button></div>}
  </div>);
}
