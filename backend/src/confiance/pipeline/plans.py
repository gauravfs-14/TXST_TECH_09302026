"""How much AI work a run does. Free tiers have small daily allowances, so the size of a run is a visible,
explicit choice, with an estimate of the calls it will make."""

PLANS = {
    "quick": {"label": "Quick check", "personas": 1, "samples": 1, "steps": 4, "max_questions": 4,
              "blurb": "Your first 4 questions, one pretend customer, one try each. Good for a first look."},
    "standard": {"label": "Standard", "personas": 2, "samples": 2, "steps": 5, "max_questions": 6,
                 "blurb": "Your first 6 questions, two pretend customers, two tries each."},
    "thorough": {"label": "Thorough", "personas": 4, "samples": 3, "steps": 6, "max_questions": 12,
                 "blurb": "Up to 12 questions, four pretend customers, three tries each. Best evidence, most AI use."},
}
DEFAULT_PLAN = "quick"
OPTIMIZER_CALLS = 10  # typical reading + proposing loop
SETUP_CALLS = 2       # knowledge base + questions (once per business)


def get(name: str | None) -> dict:
    return PLANS.get(name or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])


def _per_conv(plan: dict, judge: bool) -> int:
    return min(3, plan["steps"] - 1) + (1 if judge else 0)


def estimate_calls(n_questions: int, plan_name: str | None, judge: bool = False) -> dict:
    """Rough number of AI calls. A test conversation is about 3 calls (search, read, answer).
    'now' is what a run uses before you review it; 'later' is the smaller real-world check after you publish."""
    p = get(plan_name)
    n_questions = min(n_questions, p["max_questions"])  # a round only uses the first few questions
    prompt_sets = p["personas"] + 1  # +1 = the questions exactly as written
    per_conv = _per_conv(p, judge)
    now = 2 * prompt_sets * n_questions * p["samples"] * per_conv + OPTIMIZER_CALLS + prompt_sets + SETUP_CALLS
    later = 2 * prompt_sets * n_questions * max(1, p["samples"] - 1) * per_conv
    return {"now": int(now), "later": int(later)}
