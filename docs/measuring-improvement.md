# What Confiance measures, and why

A first real run on a small site (ComputeNepal) reported **exactly zero change** after sensible edits. The cause was
in the measurement, not the edits:

- The site appeared in the real search results in **1 of 16** practice conversations. An assistant that never sees a
  page can't be changed by editing it.
- The questions were broad ("best free resources to learn programming"), which giants like freeCodeCamp and
  Coursera dominate. No edit to one small page moves that.
- The simulated assistant answered from memory in 9 of 25 conversations, so page content was irrelevant to those.
- Seven conversations failed outright because a search returned "no results" or timed out.

## Two different questions, measured separately

| Question | Depends on | How it's measured | What helps |
|---|---|---|---|
| **Findability**: does real search show your site? | Your site's authority and how specific your pages are | Plain real searches for each question and your business name (no AI requests). Reported as-is, never simulated. | New dedicated pages for specific topics, more specific wording, being listed where assistants look ("Bigger steps") |
| **Usefulness when found**: if an assistant sees your page, does the answer use it? | The page's content | Practice rounds where **your page is guaranteed to be among the search results, in the same position, in both the "before" and "after" round** | The edits Confiance proposes |

Because the guarantee is identical in both rounds and everything else is shared (same real search results, same
questions, same pretend customers), any difference is caused by the page content. The screen says this in plain
words next to the result.

## Signals

- **Mentions you / links to you**: the answer names your business / cites your site.
- **Uses your page**: the share of the answer's 4-word phrases that appear on your page. Far more sensitive than
  "mentioned", which stays at 0 until everything else is right.
- Weights (per answer, out of 1): mention 0.20, link 0.25, uses page 0.20, page in front of assistant 0.10,
  recommended 0.25.

## Other changes made for usefulness

- The simulated assistant is told to search first, and is nudged once if it tries to answer from memory.
- A failing or empty search is no longer fatal: the assistant gets a note and can try again.
- Only the questions the proposed changes are meant to help are re-asked; before/after cover the same questions.
- Suggested questions now mix by-name, specific and broad questions instead of only broad ones.
- The optimizer sees findability, is told what tends to work (direct answers near the top, a rich FAQ, specific facts,
  structured data), and records "bigger steps" for what page edits can't fix.
- If the main model's free daily quota runs out, the round continues on the fast model instead of failing.

## Honest limits

Forcing exposure measures content quality given retrieval. It does **not** predict that the site will start
ranking: the live before/after check after publishing is the only real evidence of that, and search engines can
take weeks to re-crawl.
