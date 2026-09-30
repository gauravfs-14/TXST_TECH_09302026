// All the plain-language wording lives here so no technical term reaches the screen.
export const ASSISTANTS: Record<string, string> = { claude: "Claude", openai: "Your AI model", gemini: "Gemini" };
export const assistant = (n: string) => ASSISTANTS[n] ?? n;

export const pct = (x: number | undefined | null) => `${Math.round((x ?? 0) * 100)}%`;

/** The steps a person sees while we work. */
export const PROGRESS = [
  { key: "ready", title: "Getting ready", detail: "Reading your website and planning the practice round." },
  { key: "ask", title: "Asking AI assistants your customers' questions", detail: "We see how often they mention you today." },
  { key: "think", title: "Working out improvements", detail: "Looking for safe changes that would help." },
  { key: "test", title: "Testing the improvements", detail: "Asking the same questions again with the changes in place." },
  { key: "review", title: "Ready for your review", detail: "You decide what goes ahead." },
];
export function progressIndex(stage: string): number {
  if (["created", "kb", "prompts"].includes(stage)) return 0;
  if (stage === "baseline") return 1;
  if (stage === "optimize") return 2;
  if (["candidate", "evaluate"].includes(stage)) return 3;
  return 4;
}

export function pageName(url: string): string {
  try {
    const u = new URL(url);
    const p = u.pathname.replace(/\/$/, "");
    if (!p) return "Home page";
    return decodeURIComponent(p.split("/").pop() || "").replace(/[-_]/g, " ").replace(/\.\w+$/, "").replace(/^./, c => c.toUpperCase());
  } catch { return url; }
}

/** One friendly sentence per edit the system proposes. */
export function describeOp(op: any): string {
  switch (op.type) {
    case "set_title": return `Change the page title to “${op.text}”`;
    case "set_meta_description": return `Update the short description shown in search results: “${op.content}”`;
    case "add_faq": return `Add a questions-and-answers section (${op.items?.length ?? 0} questions) that answers what customers ask`;
    case "add_jsonld": return "Add behind-the-scenes information that helps AI assistants understand your business";
    case "insert_after": return "Add a new paragraph or section to the page";
    case "append_section": return "Add a new section at the end of the page";
    case "replace_block": return "Reword one part of the page";
    default: return "Make a small edit";
  }
}

export function friendlyBlock(v: string): string {
  if (v.includes("locked region") || v.includes("locked phrase")) return "It would have changed something you asked us to leave alone.";
  if (v.includes("numbers not found")) return "It included a number or statistic we couldn't confirm from your website.";
  if (v.includes("hidden content")) return "It used hidden text, which search engines can penalise.";
  if (v.includes("aimed at AI")) return "It tried to give instructions to AI assistants instead of writing for people.";
  if (v.includes("forbidden claim")) return "It made a claim you told us never to make.";
  if (v.includes("not in editable")) return "It was for a page you asked us not to edit.";
  if (v.includes("changes") && v.includes("existing text")) return "It would have rewritten too much of the page.";
  return "It didn't pass our safety checks.";
}

const ACTIONS: Record<string, string> = {
  "project.created": "Added your business",
  "project.updated": "Updated your settings",
  "brief.version_created": "Saved your goals and questions",
  "pages.imported": "Read pages from your website",
  "kb.built": "Learned about your business",
  "kb.skipped_unchanged": "Checked your website. Nothing had changed",
  "personas.generated": "Created pretend customers for the practice round",
  "prompts.generated": "Prepared the practice questions",
  "sim.batch_done": "Finished a practice round with AI assistants",
  "optimizer.proposal_candidate": "Suggested an improvement",
  "optimizer.proposal_blocked": "Blocked an unsafe idea",
  "optimizer.finished": "Finished working out improvements",
  "evaluation.done": "Compared results before and after",
  "proposal.approved": "You approved changes",
  "proposal.rejected": "You skipped changes",
  "deploy.started": "Started preparing the changes",
  "deploy.finished": "Changes are ready",
  "deploy.live_confirmed": "You confirmed the changes are live",
  "rollback.started": "Started undoing changes",
  "rollback.finished": "Undo is ready",
  "rollback.live_confirmed": "Changes were undone",
  "run.created": "Started looking for improvements",
  "run.failed": "Something went wrong during a run",
  "drift.checked": "Checked that AI assistants behave as before",
  "drift.baseline_accepted": "You accepted a change in an AI assistant",
  "alert.raised": "Raised a heads-up",
  "alert.acknowledged": "You dismissed a heads-up",
  "setup.config_saved": "Updated your connections",
};
export const HIDDEN_ACTIONS = ["optimizer.tool", "run.stage", "sim.", "alert.push_failed", "scheduler."];
export function describeAction(a: string): string {
  return ACTIONS[a] ?? a.replace(/[._]/g, " ").replace(/^./, c => c.toUpperCase());
}

export function friendlyDrift(engine: string, kind: string): string {
  const n = assistant(engine);
  return ({
    model_changed: `${n} switched to a different version of its AI.`,
    model_missing: `${n} has retired the AI version we were using.`,
    api_shape_changed: `${n} changed how it sends its answers.`,
    behavior_shift: `${n} is now answering differently than before.`,
    error_rate: `We couldn't get answers from ${n}.`,
  } as Record<string, string>)[kind] ?? `${n} changed.`;
}
