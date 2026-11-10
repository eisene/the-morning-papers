---
name: the-morning-headlines
description: "Use when running or configuring the user's daily AI news digest: model releases (closed and open-weights), benchmark and leaderboard news, major product launches, economics/policy/institute work and notable industry news, gathered from lab posts, model cards, press, aggregators and newsletters, merged so each story appears once with its primary source, deduped against prior runs and against The Morning Papers, and delivered by email and/or Discord. Also handles the setup interview and all feedback/config updates."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [news, ai, digest, email, discord, cron, releases, monitoring]
    related_skills: [the-morning-papers, blogwatcher, himalaya, arxiv]
---

# The Morning Headlines

Daily AI news digest: what the user would otherwise pick up from Twitter/X.
Every morning (06:45 America/New_York by default, before The Morning Papers
at 07:00) this skill gathers lab posts, model cards, press, aggregators and
newsletters, merges reports of the same story into one entry linked to the
primary source, skips everything already raised here or in The Morning
Papers, and delivers a short sectioned digest by email, Discord or both
(`delivery.method`).

It lives in the same repo as The Morning Papers and shares its core
(`digestkit/`). All of its state is under **`headlines/`** (its home):
`headlines/config/*.json`, `headlines/state/` and `headlines/digests/` are
gitignored (the repo is public; never commit personal config, interests or
email addresses). The agent NEVER hand-edits the JSON; every read/write goes
through `scripts/headlines.py`.

**Invocation note.** Run every command from the repo root as
`python3 scripts/headlines.py ...` with
`MORNING_HEADLINES_HOME=<repo>/headlines` exported (the cron prompt does
both; without it the home defaults to `<repo>/headlines` anyway). All output is
JSON on stdout. Relative file arguments to `headlines.py`, and to
`render_discord.py` / `send_email.py` with `--digest headlines`, are looked up
under the headlines home first, so `digests/D.md` means
`headlines/digests/D.md` there. When **you** write a file, use the full path
`$MORNING_HEADLINES_HOME/digests/...`: from the repo root a bare `digests/` is
the papers directory.

## When to Use

- **Daily run** (cron-triggered, or "run the morning headlines now").
- **Setup**: "set up the morning headlines" → the Interview below.
- **Feedback / config**: "more open-weights news", "skip funding rounds",
  "watch this blog", "stop reading Zvi", "that Arena item was useful", "send
  it to Discord", ... → the CLI verbs below; no run needed.

Don't use for research papers: those belong to `the-morning-papers`.

## Layout

```
headlines/config/config.json      delivery, email, digest size/age, evaluation criteria, schedule, retry
headlines/config/interests.json   topics, keywords, labs/models/products to prioritize, exclusions
headlines/config/sources.json     watch list (type, feed, filter, class)
headlines/state/seen_items.json   ledger of every story raised (keys, tags, aliases)
headlines/state/runs.jsonl        one line per run
headlines/state/feedback.jsonl    useful / not-useful verdicts
headlines/state/retry_state.json  today's attempt count + next-retry time
headlines/state/blogwatcher.db    blogwatcher-cli DB for this digest's feeds (not the papers one)
headlines/state/snapshots/        last text of leaderboard pages (snapshot diff)
headlines/digests/D.md            the digest (D = YYYY-MM-DD)
headlines/digests/D.decisions.jsonl  one line per candidate considered
headlines/digests/D.candidates.json  candidate list for `items group` (scratch)
headlines/digests/D.discord.md    the Discord copy that was posted
headlines/digests/sample.md       canonical example: follow its format, tone and structure
```

## First-Run Interview

Trigger when `python3 scripts/headlines.py status` shows `configured: false`
or the user asks. Run `python3 scripts/headlines.py init` first, then ask
conversationally, one topic at a time, writing each answer via the CLI:

1. **Delivery**: email, Discord or both? →
   `python3 scripts/headlines.py config set delivery.method email|discord|both`.
   Email reuses the papers himalaya account; just set the recipient(s):
   `python3 scripts/headlines.py config set email.to "<addr>[, <addr>]"` (and
   `email.from`, `email.transport himalaya` to match papers:
   `python3 scripts/papers.py config get email.from`). Discord: the job's
   `--deliver` target (or a post script, see Discord Delivery); nothing in config.
2. **What to prioritize**: labs, models, products →
   `interests add labs_prioritize "..."`, `models_prioritize "..."`,
   `products_prioritize "..."`; topics such as open-weights, agents, econ of AI,
   policy, chips → `interests add topics ...`, `keywords ...`.
3. **What to skip** → `interests add labs_exclude ...`, `exclude_keywords ...`
   (e.g. "crypto", "funding under $100M").
4. **Sources**: show `python3 scripts/headlines.py sources list`, confirm or
   prune (`sources disable "<name>"`), add extras with
   `sources add "<Name>" "<url>" --type lab|release|aggregator|institute|leaderboard|newsletter|arxiv|api|other --feed "<rss>" --class primary|docs|press|other|aggregator --filter "AI only"`.
   Then register the feeds with this digest's blogwatcher DB:
   `python3 scripts/headlines.py sources sync-blogwatcher --dry-run` (shows the
   adds), then without `--dry-run`.
5. **Size and verbosity** → `config set digest.target_item_count N`,
   `config set digest.top_stories 3`, `config set digest.verbosity terse|medium|detailed`.
6. **Anything else** → `interests set-instructions "<text>"`.

Finish with a `--dry-run` preview (see Dry-Run).

## Routing: headlines vs papers

Both digests read some of the same lab blogs; one item never appears in both.
Headlines runs first; papers then skips anything in this ledger (and vice
versa: `seen filter` puts the other digest's items in `peer_seen`).

- **Headlines**: releases, launches, leaderboards, benchmarks-as-news,
  business, econ / policy / institute essays.
- **Papers**: research results (papers; lab posts whose substance is a
  technical finding).
- **A model release with a tech report** goes in headlines, with the report
  linked. Record the report's arXiv id as an alias
  (`seen add <primary> ... --alias arxiv:XXXX.XXXXX`) so papers skips it. If the
  report has a real methodological contribution, leave the alias off and write
  "Tech report → see The Morning Papers" instead, but never list it in both.
- Institute essays with a companion paper (e.g. an econ.TH arXiv paper) are
  headlines; alias the paper's arXiv id.

## Daily Run Procedure

Read the state first: `python3 scripts/headlines.py status`, `config show`,
`interests show`, `sources list`, `feedback summary`. **Read
`headlines/digests/sample.md` before rendering**; it is the format reference.

### 1. Start the run

```
python3 scripts/headlines.py run start
```

Keep `run_id`, `attempt`, `max_attempts`, `wait_minutes`.

**Time window.** News from the last `digest.max_age_hours` (default 36) only.
On Mondays and after a failed day, widen it to "since the last successful
run" (`status` → `last_success.date`). Older items are only fine as context.

### 2. Gather candidates

- **Feed sources** (non-empty `feed`, tracked by blogwatcher-cli in this
  digest's own DB):
  ```
  export BLOGWATCHER_DB="$MORNING_HEADLINES_HOME/state/blogwatcher.db"
  blogwatcher-cli --db "$BLOGWATCHER_DB" scan
  blogwatcher-cli --db "$BLOGWATCHER_DB" articles
  ```
  `articles` lists only unread posts. Apply each source's `filter` (e.g.
  "AI only" for Techmeme, HN, NVIDIA, GitHub). If blogwatcher-cli is missing,
  `web_extract` the feed URLs instead.
- **Page sources** (empty `feed`): `web_extract` the URL (smol.ai AI News,
  DeepMind Institute essays, Anthropic institute/economic-index/news, Meta,
  xAI, DeepSeek, Moonshot, Z.ai release notes, MiniMax, leaderboards) and pick
  out items dated inside the window. smol.ai is the best recap of AI
  Twitter/X, but always follow its items to the primary source.
- **Hugging Face trending models**: `curl -s "https://huggingface.co/api/models?sort=trendingScore&limit=30"`.
  Drop repos tagged `uncensored`, `abliterated`, `heretic`, `gguf`, or with a
  `base_model:finetune:*` / `base_model:quantized:*` tag (re-uploads and
  community fine-tunes); keep releases by the org that trained the model, and
  only ones created inside the window or newly trending.
- **arXiv econ × AI**: the `arxiv` source URL is an API query
  (https://export.arxiv.org only). Call it **once**; on "Rate exceeded" wait
  at least 5 s before one retry, then give up for the day. Keep only entries
  published inside the window.
- **Leaderboards** (optional, low priority): to spot changes, write the page
  text to `$MORNING_HEADLINES_HOME/digests/D.<source-id>.txt` and run
  `python3 scripts/headlines.py snapshot diff "<source>" --file digests/D.<source-id>.txt --save`.
  Report a change only if it's notable (new #1, a new model entering the top 5).

For each candidate note `url`, `title`, `source` (the source name), and
entity `tags`: `lab:<org>`, `model:<name>`, `product:<name>` (lowercase,
hyphens; the CLI normalizes). Tags are how reports of the same launch with
different URLs get merged.

### 3. Dedupe and group

Write the candidates as a JSON list to
`$MORNING_HEADLINES_HOME/digests/D.candidates.json`
(`[{"url": "...", "title": "...", "source": "...", "tags": ["model:x", "lab:y"]}, ...]`)
with your file-writing tool, then:

```
python3 scripts/headlines.py items group --file digests/D.candidates.json
```

Each group has a `primary` link (lab/vendor post or model card first, then
docs/repo, then press, then aggregators), `also` links, `member_keys`, and
`seen` / `peer_seen` / `covered_on`. Drop groups that are `covered` unless
something materially new happened (a follow-up worth one line, e.g. pricing
or a reversal; say what's new). A group with `peer_seen` from papers is
already in The Morning Papers: skip it. If `primary` is an aggregator, find
and link the real primary source; if there is none, say "(unconfirmed)" or
drop it. For a quick check of plain URLs, `printf '%s\n' <url> ... |
python3 scripts/headlines.py seen filter` works too.

### 4. Select

Apply `evaluation.importance_criteria` and the interests (prioritize /
exclude lists, `exclude_keywords`, feedback). Read the primary source before
writing about it (`web_extract`), don't judge on headlines. Aim for about
`digest.target_item_count` main entries; a thin day gives a shorter digest.

### 5. Decision log (required)

Write `$MORNING_HEADLINES_HOME/digests/D.decisions.jsonl`, one JSON object
per line for **every** candidate group member you considered:

```
{"id": "<url or key>", "title": "...", "source": "...", "opened": true, "decision": "main", "reason": "...", "section": "model-releases"}
```

- `decision`: `main` (in a main section, incl. Top Stories and Worth
  reading), `near-miss` (in Also notable, or considered and narrowly cut),
  `dropped`.
- `opened`: whether you read the page.
- `section` (optional): `top-stories`, `model-releases`, `benchmarks`,
  `product-launches`, `econ-policy`, `industry`, `worth-reading`, `also-notable`.
- `merged_into` (optional): for a group member that isn't the primary, the
  primary's id; its decision is `dropped` (it may still appear as an *Also:* link).

Then validate it against the digest (after step 6, re-run if you change the digest):

```
python3 scripts/headlines.py decisions check digests/D.decisions.jsonl --digest-file digests/D.md
```

Exit 0 = consistent. Fix every `errors`, `missing_from_log` (a main-section
link with no `main` entry) and `main_missing_from_digest` entry and re-run.

### 6. Render

Write `$MORNING_HEADLINES_HOME/digests/D.md` following
`headlines/digests/sample.md` and `email.style_instructions` (the sample wins
on conflicts). Sections, in this order, skipping empty ones:

1. `## ⭐ Top Stories`: `digest.top_stories` (3) numbered lines,
   `1. **[Title](primary)**: what happened, why it matters.` The post script
   uses the first `1.` line under this heading as the thread title, so keep
   that line self-contained. Top stories are **not** repeated below.
2. `## Model releases`: mark `[open-weights]` and/or `[API]`.
3. `## Benchmarks & leaderboards`
4. `## Product launches`
5. `## Economics, policy & institutes`
6. `## Industry & business`
7. `## Worth reading`: one line per newsletter essay, link + why.
8. `## Also notable`: one-liners for things just below the bar.

Entry format: `- **[Title](primary)**: what happened, why it matters. *Also:* [TechCrunch](...), [smol.ai](...)`.
Every entry links its primary source. No hype words; numbers over adjectives.

### 7. Record seen

Mark every **main-section** story seen, Top Stories and Worth reading
included, with its tags, and with aliases for linked tech-report arXiv ids
and for the group's other member URLs worth catching tomorrow:

```
python3 scripts/headlines.py seen add "<primary url>" --title "<title>" --source "<source>" --run-id <run_id> --section model-releases --tag lab:northwind --tag model:aurora-3 --alias arxiv:XXXX.XXXXX
```

**Never** mark Also notable one-liners seen; they may come back with more
substance.

### 8. Deliver

`delivery_method` from `status` (missing = `email`).

**Email** (`email` or `both`):
```
uv run scripts/send_email.py --digest headlines --body-file digests/D.md
```
Subject defaults to `The Morning Headlines — {date}`. Exit 0 = sent. Without
`uv`: `python3 scripts/send_email.py --digest headlines ...`.

**Discord** (`discord` or `both`):
```
python3 scripts/render_discord.py --digest headlines --body-file digests/D.md --out digests/D.discord.md
```
If `over_budget: true`, write a shorter `$MORNING_HEADLINES_HOME/digests/D.discord-src.md`
(trim Also notable and Worth reading first, then shorten entries; keep every
main story and its primary link), render that to `digests/D.discord.md`, and
repeat until it fits. Never post it yourself with a send-message tool: your
final response, after step 9, is **exactly** the contents of
`digests/D.discord.md`, nothing before or after.

### 9. Finish

```
blogwatcher-cli --db "$MORNING_HEADLINES_HOME/state/blogwatcher.db" read-all --yes
python3 scripts/headlines.py run finish <run_id> success --attempt <n> --sections <k> --items <key1> <key2> ...
```

## Failure & Retry (max 3 attempts/day, 20-min backoff)

If a step fails hard (network, send error, a gather that looks broken):

```
python3 scripts/headlines.py run finish <run_id> failed --attempt <n> --error "<what broke>" --wait-minutes 20
python3 scripts/headlines.py run should-retry
```

`should_retry: true` → wait `wait_minutes`, restart at step 1 (the attempt
count lives in `retry_state.json`, keyed by date). `false` → stop and tell the
user today's digest failed, with the last error. The counter resets on success
or the next day. A single unreachable source is not a failure: note it and
carry on.

## Dry-Run

No state changes (retry, ledger, run history):

| Normal step | Dry-run |
|---|---|
| `run start` | `run start --dry-run` → `run_id: "dry-run-YYYY-MM-DD"` |
| `seen add ...` | `seen add ... --dry-run` |
| `run finish ...` | `run finish ... --dry-run` |
| `send_email.py --digest headlines ...` | add `--dry-run` |
| `blogwatcher-cli read-all` | skip it |
| Discord final response | show the rendered text instead |

`items group`, `seen filter`, `seen has`, `decisions check`, `snapshot diff`
(without `--save`), `blogwatcher-cli scan` / `articles` are read-only.

## Feedback & Config Verbs

| User says | Command |
|---|---|
| prioritize / skip a lab, model, product, topic | `python3 scripts/headlines.py interests add\|remove <field> "v1" "v2"`; fields: `topics keywords labs_prioritize labs_exclude models_prioritize products_prioritize exclude_keywords` |
| standing instruction | `python3 scripts/headlines.py interests set-instructions "<text>"` |
| "story X was useful / useless" | `python3 scripts/headlines.py feedback add "<url>" useful\|not-useful --note "<why>" --source "<source>"` |
| review feedback | `python3 scripts/headlines.py feedback summary` |
| watch a source | `python3 scripts/headlines.py sources add "<Name>" "<url>" --type <type> --feed "<rss>" --class <class> --filter "<filter>"`, then `sources sync-blogwatcher` if it has a feed |
| stop / resume a source | `python3 scripts/headlines.py sources disable "<name>"` / `sources enable "<name>"` |
| a source has been great / bad | `python3 scripts/headlines.py sources bump "<name>" <+/-N>` |
| change the bar | `python3 scripts/headlines.py config set evaluation.importance_criteria "<text>"` |
| size / top stories / verbosity / age | `config set digest.target_item_count N`, `digest.top_stories N`, `digest.verbosity terse\|medium\|detailed`, `digest.max_age_hours N` |
| email address / subject / style | `config set email.to <addr>`, `email.subject_template "... {date}"`, `email.style_instructions "<text>"` |
| email ↔ Discord | `config set delivery.method email\|discord\|both` |

Echo back the value the CLI prints. Resolve references like "the second
release" against `headlines/digests/D.md` for the date of the post.

## Discord Delivery

As for papers: the Hermes gateway posts the cron job's final response. Either
create the job with `--deliver discord:<channel_id>`, or deliver `local` and
let a no-agent post job read the output and open its own thread, using the
first `1.` line under `⭐ Top Stories` as the thread title. Only the digest's
owner may change its config, interests, sources or feedback on a shared bot.

## Common Pitfalls

1. **Hand-editing JSON.** Use the CLI.
2. **Aggregator claims without the primary source.** smol.ai, Techmeme, HN and
   newsletters point at news; link and check the lab post, model card, docs,
   filing or official statement. Rumours stay out unless the user asked.
3. **Stale news.** Respect the time window; a re-shared month-old launch isn't news.
4. **Double-listing with The Morning Papers.** Honor `peer_seen`; record
   arXiv aliases for tech reports you link.
5. **Duplicates within the digest.** One story, one entry: merge via tags and
   `items group`, put other coverage under *Also:*.
6. **Writing to the wrong digests/.** From the repo root `digests/` is papers';
   write to `$MORNING_HEADLINES_HOME/digests/`.
7. **No `python3 -c` / `-e`, no heredoc Python, no `execute_code` in cron.**
   The command classifier blocks them. Read state with `headlines.py`
   subcommands and `grep`; write JSON inputs with your file tool and pass
   `--file`.
8. **Plain `http://` in curl/wget.** Blocked in cron; always `https://`
   (arXiv: https://export.arxiv.org).
9. **Hammering arXiv.** One econ query per run, ≥5 s before a retry.
10. **Marking Also notable seen.** Don't; it can return with substance.
11. **Resetting retries.** Never `init --force` after a failure.

## Verification Checklist

- [ ] `status` shows `configured: true` before a run.
- [ ] Every candidate grouped; covered and `peer_seen` groups skipped.
- [ ] Primary sources read for every main story; every entry linked.
- [ ] `digests/D.decisions.jsonl` written; `decisions check ... --digest-file` exits 0.
- [ ] Main-section stories recorded with `seen add` (tags, aliases); Also notable not.
- [ ] Delivered (email exit 0 and/or Discord copy under budget as the final response) or failure recorded.
- [ ] `blogwatcher-cli read-all --yes` (headlines DB) and `run finish` called.
