---
name: the-morning-papers
description: "Use when running or configuring the user's daily AI-paper digest — pull arXiv + Hugging Face + watched blogs, filter for novelty against stated interests, dedupe against prior runs, organize into sections, and email a TL;DR digest. Also handles the setup interview and all feedback/config updates (interests, sources, usefulness, evaluation criteria, digest size, email settings)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [research, arxiv, digest, email, cron, papers, monitoring]
    related_skills: [arxiv, blogwatcher, himalaya]
---

# The Morning Papers

Daily AI research digest. Every morning at 10:00 America/New_York this skill
pulls new arXiv papers + the Hugging Face trending feed + a watch-list of lab
blogs, keeps only genuinely novel work matching the user's interests, dedupes
against everything raised before, organizes the survivors into sections, and
emails a clean TL;DR Markdown digest.

All persistent state lives in **this repo** (version-controlled, private). The
agent NEVER hand-edits the JSON — every read/write goes through
`scripts/papers.py`. Email goes through `scripts/send_email.py`.

## When to Use

- **Daily run** (cron-triggered or "run the morning papers now").
- **Setup**: "set up the morning papers" → run the Interview (below).
- **Feedback / config**: any of "add topic X", "I found paper Y useful", "watch
  this blog", "stop watching Z", "make it 3 sections", "change the novelty bar",
  "update my email / subject / style". Route these to the CLI verbs below — no
  full run needed.

Don't use for: one-off literature searches (use the `arxiv` skill directly).

## Layout

```
config/config.json        email, digest size, evaluation criteria, schedule, retry
config/interests.json     topics, keywords, authors/labs to prioritize or exclude
config/sources.json       watch list (blogs, arxiv feeds, trending sources)
state/seen_papers.json    dedup ledger of every paper ever raised
state/runs.jsonl          one line per run (success/failed, papers, sections)
state/feedback.jsonl      useful / not-useful verdicts
state/retry_state.json    today's attempt count + next-retry timestamp
digests/YYYY-MM-DD.md     the rendered digest that was emailed
```

Set `MORNING_PAPERS_HOME` to the repo root before every CLI call (the cron
prompt does this). All `papers.py` output is JSON on stdout.

## First-Run Interview

Trigger when config is unset (`papers.py status` shows `configured: false`) or
the user asks to set up. Run `papers.py init` first, then ask these, in order,
and write each answer via the CLI. Ask them conversationally; don't dump all at
once. Confirm the seed blog list explicitly.

1. **Email address** — where digests go. → `config set email.to <addr>`
   (also ask the From address if different → `config set email.from <addr>`).
2. **Topics / keywords** — initial interests. → `interests add topics ...` and
   `interests add keywords ...`.
3. **Labs / authors to prioritize or exclude**. →
   `interests add labs_prioritize ...`, `interests add authors_exclude ...`, etc.
4. **Seed blog list** — show `sources list`, confirm/prune. Add extras with
   `sources add`, drop unwanted with `sources disable`.
5. **Digest length / verbosity** — terse | medium | detailed. →
   `config set digest.verbosity <v>`.
6. **Digest cap size** — target sections and total papers. →
   `config set digest.target_sections N`, `config set digest.target_paper_count N`.
   (These are guidelines, not hard limits — tell the agent so at run time.)
7. **Any additional instructions** — free text. →
   `interests set-instructions "<text>"` and/or the email style
   (`config set email.style_instructions "<text>"`) and subject
   (`config set email.subject_template "... {date}"`).

Finish by confirming email transport works (see Email Delivery) and offering a
`--dry-run` preview.

## Daily Run Procedure

Read the current config first: `papers.py status`, `config show`,
`interests show`, `sources list`, and `feedback summary` (recent verdicts steer
selection). Then:

### 1. Start the run (registers the attempt)

```
papers.py run start
```

Capture `run_id`, `attempt`, `max_attempts`, `wait_minutes` from the JSON.

### 2. Gather candidates

- **arXiv**: for each `type:arxiv` source and the user's topics/keywords, query
  the arXiv API (see the `arxiv` skill). Pull the last ~24-48h of `cs.LG/cs.CL/
  cs.AI` plus targeted keyword queries. Prefer `sortBy=submittedDate`.
- **Hugging Face papers**: `web_extract` on `https://huggingface.co/papers`
  (and `?date=YYYY-MM-DD`) to get trending/upvoted items.
- **Blogs & other sources**: two paths depending on whether a feed is set.
  - *Feed-backed blogs* (sources with a non-empty `feed`, tracked by
    blogwatcher-cli): run one scan, then read only new posts. Set the DB path so
    state lives in the repo:
    ```
    export BLOGWATCHER_DB="$MORNING_PAPERS_HOME/state/blogwatcher.db"
    blogwatcher-cli scan            # detects new posts across all tracked feeds
    blogwatcher-cli articles        # lists only UNREAD (new since last run)
    ```
    `web_extract` the URLs of interesting new articles for judging, then
    `printf 'y\n' | blogwatcher-cli read-all` once the run succeeds so they don't
    resurface tomorrow. blogwatcher keeps its own read/unread state — this is the
    "what's new since yesterday" detector for blogs. If blogwatcher-cli isn't
    installed, fall back to `web_extract` on each feed URL.
  - *Feedless blogs* (empty `feed`: e.g. Anthropic, Meta, DeepSeek, Moonshot,
    Z.ai, MiniMax, Cohere, AI2, Physical Intelligence, Prime Intellect, Berkeley
    RAIL, Stanford IRIS): `web_extract` the URL directly and note anything new
    vs. the last run. These are NOT in blogwatcher (they have no discoverable
    RSS, and a feedless source hangs `scan`).

### 3. Dedupe

Collect all candidate ids/urls, then filter out already-raised ones:

```
printf '%s\n' <id-or-url per line> | papers.py seen filter
```

Only work with the returned `unseen` keys.

### 4. Select for novelty & relevance

Apply `evaluation.novelty_criteria` + `evaluation.usefulness_criteria` from
config against the user's interests. **Filter out minor tweaks** to training
protocols, incremental benchmark bumps, and routine scaling reports unless they
carry a genuinely new idea. Honor `authors_exclude`/`labs_exclude`. Boost items
from high-`usefulness` sources and topics the user marked useful in feedback.
Read abstracts (`web_extract` on the abstract page) before judging — don't
select on title alone.

### 5. Organize

Cluster survivors into ~`digest.target_sections` themed sections, most
novel/important first, aiming for ~`digest.target_paper_count` total. These are
**guidelines** — go over or under when the day's crop justifies it. De-duplicate
near-identical papers, merge cross-posts.

**"Near-miss" section.** If `interests.extra_instructions` requests it (a
standing preference by default), add a "Didn't quite make the cut" section after
the main sections with 3-5 papers that were relevant but fell just below the bar
— one skimmable line each: link, what it is, why it was borderline. These do
**not** count toward `digest.target_paper_count` and are **NOT** marked seen in
step 6, so they can resurface if they gain traction.

### 6. Render + record

Write the digest to `digests/YYYY-MM-DD.md` following `email.style_instructions`
(TL;DR: one-line takeaway per paper, 1-2 sentences on why it matters / what's
novel, every paper linked, clear section headers). Then mark each raised paper
seen — **main-section papers only, never the near-miss list**:

```
papers.py seen add "<url-or-id>" --title "<title>" --source "<source name>" --run-id <run_id>
```

### 7. Email

```
uv run scripts/send_email.py --body-file digests/YYYY-MM-DD.md
```

Verify exit code 0. (Use `--dry-run` first if unsure.) `uv run` provisions the
`markdown` package (declared as a PEP 723 dep) in a cached ephemeral env, so
digests render tables, fenced code, and nested lists with no venv to manage. If
`uv` is unavailable, fall back to `python3 scripts/send_email.py ...` — it uses
`markdown` if installed, else a stdlib renderer for headings/lists/links.

### 8. Finish

On success:
```
papers.py run finish <run_id> success --attempt <n> --sections <k> --papers <id1> <id2> ...
```

## Failure & Retry (max 3 attempts/day, 20-min backoff)

If ANY step fails hard (network, email bounce, empty pull that looks broken),
record the failure and consult retry state:

```
papers.py run finish <run_id> failed --attempt <n> --error "<what broke>" --wait-minutes 20
papers.py run should-retry
```

- If `should_retry: true` → **wait** the configured `wait_minutes` (default 20),
  then start a fresh attempt at step 1. Attempts persist in `retry_state.json`
  keyed by date, so a re-invoked cron run continues the count rather than
  resetting it.
- If `should_retry: false` (3 attempts exhausted) → stop and email/notify the
  user that today's digest failed, including the last error. Do not keep trying.

The retry counter auto-resets on the next calendar day or on any success.

## Feedback & Config Verbs (no run needed)

Route natural-language requests to these. All take `MORNING_PAPERS_HOME` in env.

| User says | Command |
|-----------|---------|
| add/remove a topic, keyword, author, lab | `papers.py interests add\|remove <field> "v1" "v2"` — fields: `topics keywords authors_prioritize authors_exclude labs_prioritize labs_exclude` |
| general standing instruction | `papers.py interests set-instructions "<text>"` |
| "I found paper X useful/useless" | `papers.py feedback add "<url-or-id>" useful\|not-useful --note "<why>" --source "<source>"` |
| watch a new source | `papers.py sources add "<Name>" "<url>" --type blog\|arxiv\|trending\|other --feed "<rss?>"` |
| stop watching a source | `papers.py sources disable "<name>"` (or `remove <name> --hard` to delete) |
| a source has been great/bad | `papers.py sources bump "<name>" <+/-N>` |
| change novelty/usefulness/organization bar | `papers.py config set evaluation.novelty_criteria "<text>"` (or `.usefulness_criteria`, `.organization`) |
| change section / paper targets | `papers.py config set digest.target_sections N` / `digest.target_paper_count N` |
| change verbosity | `papers.py config set digest.verbosity terse\|medium\|detailed` |
| change email address / from | `papers.py config set email.to <addr>` / `email.from <addr>` |
| change subject line | `papers.py config set email.subject_template "... {date}"` |
| change email style | `papers.py config set email.style_instructions "<text>"` |

After any change, echo back the resulting value (the CLI prints it) so the user
sees it took effect.

## Email Delivery

`send_email.py` picks a transport from `email.transport` (`auto` by default):

- **himalaya**: if the `himalaya` CLI is configured (see the `himalaya` skill),
  `auto` uses it — no extra secrets needed here.
- **smtp**: set `smtp.host`, `smtp.port`, `smtp.username`, and put the password
  in the env var named by `smtp.password_env` (default
  `MORNING_PAPERS_SMTP_PASSWORD`). Never commit the password.

Always `--dry-run` once when first configuring to confirm the rendered HTML +
recipient look right.

## Common Pitfalls

1. **Editing JSON by hand.** Don't. Use the CLI so schema/dedup stay consistent.
2. **Selecting on titles.** Read abstracts before judging novelty.
3. **Forgetting to mark seen.** If you email a paper without `seen add`, it will
   resurface tomorrow. Mark every raised paper.
4. **Resetting retries.** Never `init --force` on a failure; the retry count
   lives in `retry_state.json` and must survive across re-invocations.
5. **Hard section/paper limits.** The targets are guidelines; a thin news day
   should produce a shorter digest, not padding.
6. **Committing secrets.** SMTP passwords go in env vars, never the repo.

## Verification Checklist

- [ ] `papers.py status` shows `configured: true` before a run.
- [ ] Candidates deduped via `seen filter`; only unseen carried forward.
- [ ] Abstracts read for every selected paper.
- [ ] Digest written to `digests/YYYY-MM-DD.md`, every paper linked.
- [ ] Every raised paper recorded with `seen add`.
- [ ] Email sent (exit 0) or failure recorded + retry logic followed.
- [ ] `run finish` called with the correct status.
