// Plain-language wording lives here so no technical term reaches the screen.
export const ASSISTANTS: Record<string, string> = { claude: "Claude", openai: "Your AI model", gemini: "Gemini" };
export const assistant = (n: string) => ASSISTANTS[n] ?? n;

/** The pipeline, in the order the person thinks about it. */
export const PIPELINE = [
  { key: "requirements", title: "Requirements", detail: "Working out what to measure: your questions and products." },
  { key: "research", title: "Research", detail: "Checking how search and AI assistants see you, and who wins today." },
  { key: "baseline", title: "Baseline", detail: "Testing today's pages so there's a fair 'before'." },
  { key: "loop", title: "Draft & test", detail: "Drafting changes, then testing them in a sandbox. Repeats up to your limit." },
  { key: "finalize", title: "Plan & report", detail: "Choosing the best draft and writing your plan and report." },
  { key: "review", title: "Your review", detail: "You decide what goes ahead." },
  { key: "deploy", title: "Publish", detail: "Apply the changes, then measure the real effect." },
];
export function pipelineIndex(stage: string): number {
  const legacy: Record<string, string> = { created: "requirements", kb: "requirements", prompts: "requirements", optimize: "loop", candidate: "loop", evaluate: "finalize" };
  const s = legacy[stage] ?? stage;
  if (s === "awaiting_approval") return 5;
  if (["deploy", "awaiting_live", "awaiting_measure", "measure", "done"].includes(s)) return 6;
  const i = PIPELINE.findIndex(p => p.key === s);
  return i < 0 ? 0 : i;
}
export const isWorking = (r: any) => !!r && (r.status === "running" || r.status === "pending");

export function pageName(url: string): string {
  try {
    const u = new URL(url), p = u.pathname.replace(/\/$/, "");
    if (!p) return "Home page";
    return decodeURIComponent(p.split("/").pop() || "").replace(/[-_]/g, " ").replace(/\.\w+$/, "").replace(/^./, c => c.toUpperCase());
  } catch { return url; }
}
export const pathOf = (url: string) => { try { return new URL(url).pathname || "/"; } catch { return url; } };
export const host = (url: string) => url.replace(/^https?:\/\//, "").replace(/\/$/, "");

export function describeOp(op: any): string {
  switch (op.type) {
    case "set_title": return `Change the page title to “${op.text}”`;
    case "set_meta_description": return `Update the search-result description: “${op.content}”`;
    case "add_faq": return `Add a questions-and-answers section (${op.items?.length ?? 0} questions)`;
    case "add_jsonld": return "Add behind-the-scenes information that helps AI assistants understand the page";
    case "insert_after": return "Add a new paragraph or section";
    case "append_section": return "Add a new section at the end of the page";
    case "replace_block": return "Reword one part of the page";
    case "create_page": return `Create a new page: ${op.title}`;
    default: return "Make a small edit";
  }
}
export function friendlyBlock(v: string): string {
  if (v.includes("locked region") || v.includes("locked phrase")) return "It would have changed something you asked us to leave alone.";
  if (v.includes("numbers not found")) return "It included a number or statistic we couldn't confirm from your website.";
  if (v.includes("hidden")) return "It used hidden text, which search engines can penalise.";
  if (v.includes("AI models")) return "It tried to give instructions to AI assistants instead of writing for people.";
  if (v.includes("forbidden claim")) return "It made a claim you told us never to make.";
  if (v.includes("too thin")) return "The page it wrote was too thin to be useful.";
  if (v.includes("word for word")) return "The new page repeated an existing page.";
  if (v.includes("at most")) return "It would have added more new pages than your limit allows.";
  if (v.includes("switched off")) return "New pages are switched off in your settings.";
  if (v.includes("outside the pages")) return "It was for a page you asked us not to edit.";
  if (v.includes("existing text")) return "It would have rewritten too much of the page.";
  return "It didn't pass our safety checks.";
}

const ACTIONS: Record<string, string> = {
  "project.created": "Added your business", "project.updated": "Updated your settings", "brief.version_created": "Saved your goals and questions",
  "pages.imported": "Read pages from your website", "site.scanned": "Scanned your website", "kb.built": "Learned about your business", "kb.skipped_unchanged": "Checked your website. Nothing had changed",
  "requirements.set": "Chose what to measure", "sim.batch_done": "Finished a practice round with an AI assistant", "loop.done": "Finished a draft-and-test loop",
  "optimizer.proposal_candidate": "Drafted a change", "optimizer.proposal_blocked": "Blocked an unsafe idea", "optimizer.finished": "Finished drafting",
  "evaluation.done": "Compared results before and after", "proposal.approved": "You approved changes", "proposal.rejected": "You skipped changes",
  "deploy.started": "Started preparing the changes", "deploy.finished": "Changes are ready", "deploy.live_confirmed": "You confirmed the changes are live",
  "rollback.started": "Started undoing changes", "rollback.finished": "Undo is ready", "rollback.live_confirmed": "Changes were undone",
  "run.created": "Started a round", "run.failed": "Something went wrong during a round", "run.cancelled": "A round was stopped", "run.interrupted": "A round was interrupted by a restart",
  "drift.checked": "Checked that AI assistants behave as before", "drift.baseline_accepted": "You accepted a change in an AI assistant", "alert.raised": "Raised a heads-up",
  "alert.acknowledged": "You dismissed a heads-up", "setup.config_saved": "Updated your connections", "settings.updated": "Changed your optimization settings",
  "plan.status": "Updated a step in your plan", "plan.partial": "The plan was only partly written", "product.added": "Added a product", "product.updated": "Edited a product",
  "product.deleted": "Removed a product", "products.imported": "Imported products",
};
export const HIDDEN_ACTIONS = ["optimizer.tool", "run.stage", "sim.", "alert.push_failed", "scheduler.", "run.cancel_requested"];
export const describeAction = (a: string) => ACTIONS[a] ?? a.replace(/[._]/g, " ").replace(/^./, c => c.toUpperCase());

export function friendlyDrift(engine: string, kind: string): string {
  const n = assistant(engine);
  return ({ model_changed: `${n} switched to a different version of its AI.`, model_missing: `${n} has retired the AI version we were using.`, api_shape_changed: `${n} changed how it sends its answers.`,
    behavior_shift: `${n} is now answering differently than before.`, error_rate: `We couldn't get answers from ${n}.` } as Record<string, string>)[kind] ?? `${n} changed.`;
}

export const CATEGORY: Record<string, { label: string; tone?: string }> = {
  content: { label: "Content" }, technical: { label: "Technical SEO" }, structured_data: { label: "Structured data" }, off_page: { label: "Off-page" }, products: { label: "Products" }, measurement: { label: "Measurement" },
};
export const FIT: Record<string, { label: string; tone: "good" | "warn" | "bad" }> = {
  winning: { label: "Winning", tone: "good" }, in_reach: { label: "In reach", tone: "warn" }, needs_content: { label: "Needs a new page", tone: "bad" },
};
export const SEVERITY: Record<string, { label: string; tone: "bad" | "warn" | "clay" | undefined }> = { high: { label: "High", tone: "bad" }, medium: { label: "Medium", tone: "warn" }, low: { label: "Low", tone: "clay" }, info: { label: "Info", tone: undefined } };
export const PRIORITY_TEXT: Record<string, string> = { P0: "Do first", P1: "Next", P2: "Soon", P3: "Later" };
export const VERDICT: Record<string, { label: string; tone: "good" | "warn" | "bad" | undefined }> = {
  improved: { label: "Clear improvement", tone: "good" }, inconclusive: { label: "Inconclusive", tone: "warn" }, no_change: { label: "No meaningful change", tone: undefined }, worse: { label: "Made things worse", tone: "bad" }, no_changes: { label: "Nothing to change", tone: undefined },
};
export const STOP_REASON: Record<string, string> = { "stop:max_loops": "reached your loop limit", "stop:plateau": "further loops stopped helping", "stop:converged": "nothing more to improve", "stop:no_changes": "no safe changes to draft", continue: "still going" };

/** A round's stored error, in words a person can act on. */
export function friendlyError(e: string | null | undefined): { text: string; raw: string } {
  const raw = (e ?? "").trim();
  if (/503|UNAVAILABLE|high demand|overloaded/i.test(raw)) return { text: "The AI service was too busy to answer. This usually passes within a few minutes, so try again shortly.", raw };
  if (/429|rate.?limit|quota/i.test(raw)) return { text: "The AI service says we've hit its request limit. Wait a little, or switch to a plan or model with a higher limit, then try again.", raw };
  if (/401|403|api key|unauthor/i.test(raw)) return { text: "The AI service didn't accept your key. Check the AI connection in Settings.", raw };
  if (/timeout|timed out|connection/i.test(raw)) return { text: "We lost the connection to the AI service part-way through. Try again.", raw };
  return { text: raw.replace(/^\w+(Error|Exception): /, "") || "Something went wrong.", raw };
}
