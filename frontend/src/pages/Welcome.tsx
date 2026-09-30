import { useEffect, useState } from "react";
import { api } from "../api";
import { Button, Card, Icon } from "../ui";
import { AiModelForm, SearchForm } from "./Accounts";

export function Welcome({ status, onReady }: { status: Record<string, boolean>; onReady: () => void }) {
  const [cfg, setCfg] = useState<any>(null);
  const load = () => api("/setup/config").then(setCfg);
  useEffect(() => { load(); }, []);
  return (<div className="narrow space-y-3.5">
    <div className="text-center mt-4 mb-8">
      <span className="inline-block text-primary"><Icon n="leaf" size={44} /></span>
      <h1 className="mt-2">Welcome to Confiance</h1>
      <p className="text-muted-foreground text-lg">People now ask AI assistants like ChatGPT for advice instead of searching Google.
        Confiance helps those assistants find your business and describe it accurately.</p>
    </div>
    <Card title="First, connect an AI model">
      <p className="text-muted-foreground">Confiance needs an AI to do its thinking. You can use one that runs free on your own computer, or an online service. You only do this once.</p>
      {cfg && <AiModelForm cfg={cfg} onDone={() => { load(); onReady(); }} />}
    </Card>
    <Card title="Then, how should we look things up?">
      <p className="text-muted-foreground">The free option works without any account. You can change this later in Settings.</p>
      {cfg && <SearchForm cfg={cfg} onDone={() => { load(); onReady(); }} />}
    </Card>
    {status.llm && status.search && <div className="text-center"><Button size="big" onClick={onReady}>Continue <Icon n="arrow" /></Button></div>}
  </div>);
}
