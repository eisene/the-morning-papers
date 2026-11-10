# the-morning-papers

Two daily AI digests for Hermes, built on one shared core:

| Digest | Skill | What | Default time (America/New_York) |
|---|---|---|---|
| **The Morning Papers** | `SKILL.md` (`the-morning-papers`) | genuinely novel AI research: arXiv, Hugging Face papers, lab research blogs | 07:00 |
| **The Morning Headlines** | `headlines/SKILL.md` (`the-morning-headlines`) | AI news: model releases, benchmarks & leaderboards, launches, econ/policy/institute work, industry | 06:45 |

Each one filters to your interests, dedupes against everything it (and the
other digest) has raised before, and arrives by email, in a Discord channel,
or both.

## What the papers digest does

1. Pulls new arXiv papers, the Hugging Face trending feed, and a watch-list of
   lab blogs (OpenAI, Anthropic, DeepMind, Meta, Google, plus anything you add).
2. Keeps only novel, relevant work — filters out minor training-protocol tweaks,
   incremental benchmark bumps, and routine scaling reports.
3. Dedupes against every paper raised in prior runs.
4. Clusters survivors into sections and renders a clean Markdown digest.
5. Emails it to you and/or posts it to Discord through the Hermes gateway.
6. On failure: waits 20 minutes and retries, up to 3 attempts per day.

## What the headlines digest does

1. Reads aggregators (smol.ai AI News, Techmeme, HN, TechCrunch, The Verge),
   lab and vendor posts, the Hugging Face trending-models API, institutes and
   policy sources (DeepMind Institute, Epoch, METR, NBER, an arXiv econ × AI
   query, Anthropic's institute pages), leaderboards (LMArena, Artificial
   Analysis) and newsletters.
2. Merges reports of the same story (`items group`: canonical URLs plus
   `model:`/`product:` tags) into one entry linked to the primary source, with
   the press and aggregator coverage as *Also:* links.
3. Skips stories already raised here or in The Morning Papers.
4. Renders sections: ⭐ Top Stories, Model releases (`[open-weights]` /
   `[API]`), Benchmarks & leaderboards, Product launches, Economics, policy &
   institutes, Industry & business, Worth reading, Also notable. See
   `headlines/digests/sample.md`.

## Layout

```
digestkit/            shared core (stdlib only)
  core.py             spec-driven state CLI: config, interests, sources, seen, feedback, run, ...
  specs/papers.py     papers defaults, 17 seed sources, ledger state/seen_papers.json ("papers")
  specs/headlines.py  headlines defaults, seed sources, sections, domain classes
  urls.py             URL canonicalization, item keys, cross-digest match keys
  items.py            grouping of headline candidates (items group)
  discord.py          Discord rendering (scripts/render_discord.py)
  mailer.py           email delivery (scripts/send_email.py)
scripts/papers.py     papers CLI (thin wrapper; same CLI and files as always)
scripts/headlines.py  headlines CLI (same verbs)
scripts/render_discord.py, send_email.py   shared; --digest papers|headlines (default papers)
SKILL.md              the papers skill;   headlines/SKILL.md  the headlines skill
config/ state/ digests/                    papers home (repo root)
headlines/config/ headlines/state/ headlines/digests/   headlines home
```

| Path (per digest home) | Purpose |
|------|---------|
| `config/` | `config.json`, `interests.json`, `sources.json`: personal config, gitignored; created by `init` from the spec's defaults. |
| `state/` | the seen ledger (`seen_papers.json` / `seen_items.json`), `runs.jsonl`, `feedback.jsonl`, `retry_state.json`, `blogwatcher.db` (one per digest), `snapshots/` (headlines): local, gitignored. |
| `digests/` | `YYYY-MM-DD.md`, `.discord.md`, `.decisions.jsonl`: generated, gitignored; only `sample.md` is tracked. |

Other files: `scripts/setup_email.sh` (`make setup-email`, interactive Gmail +
himalaya setup), `docs/email-setup.md`, `tests/`, `Makefile`.

### What the core shares, what a spec sets

| Shared (`digestkit`) | Per digest (`DigestSpec`) |
|---|---|
| CLI verbs, JSON output, retry/run logic, feedback | name, title, home env var + default home |
| ledger matching, peer dedup, `items group`, `decisions check`, `snapshot` | ledger file + key, item key function |
| Discord rendering, email (himalaya/SMTP) | default config / interests / sources, source types |
| | subject template, SMTP password env var, peer digests |

### Environment

| Variable | Default | Used by |
|---|---|---|
| `MORNING_PAPERS_HOME` | repo root | papers CLI, `send_email.py`, headlines' peer lookup |
| `MORNING_HEADLINES_HOME` | `<repo>/headlines` | headlines CLI, `--digest headlines`, papers' peer lookup |
| `BLOGWATCHER_DB` | — | set to `<home>/state/blogwatcher.db` for each digest |
| `MORNING_PAPERS_SMTP_PASSWORD` / `MORNING_HEADLINES_SMTP_PASSWORD` | — | SMTP transport only |

`--home <dir>` (before the subcommand) overrides the env var for one call.
The scripts work from the repo root (`python3 scripts/X.py`) or by absolute
path from any directory.

### Cross-digest dedup

Each digest has its own ledger but `seen has`, `seen filter` and `items group`
also check the other one (its home from its env var, else its default
location; a missing ledger is fine). Hits are reported as `peer_seen` and
left out of `unseen`. Matching uses a set of keys per item (arXiv id,
canonical URL, and the papers digest's original `url:<sha1>` key), so the two
key schemes meet: papers keeps storing its old keys (new records also keep the
raw `url`), headlines stores readable ones (`arxiv:`, `hf:org/model`,
`gh:owner/repo`, `url:<canonical url>`) plus tags and aliases.

Routing: research results go to papers; releases, launches, leaderboards,
business and econ/policy/institute essays go to headlines. A model release
with a tech report goes in headlines, which records the report's arXiv id as
an alias so papers skips it.

## Setup

```bash
export MORNING_PAPERS_HOME=$(pwd)
python3 scripts/papers.py init
make setup-email      # email only: himalaya v2 + Gmail app password, test email
```

Delivery is `email` (default), `discord`, or `both`:

```bash
python3 scripts/papers.py config set delivery.method discord
```

The email setup asks where to keep the Gmail app password (a private file,
macOS Keychain, or a Linux desktop keyring). See
[docs/email-setup.md](docs/email-setup.md) for the trade-offs.

Then ask Hermes to "set up the morning papers" — it runs an interview for
delivery (email address and/or Discord channel), topics/keywords, labs/authors,
seed blog confirmation, digest verbosity and cap size, and any extra
instructions.

### Setup: The Morning Headlines

```bash
make init-headlines                       # = MORNING_HEADLINES_HOME=$(pwd)/headlines python3 scripts/headlines.py init
H="python3 scripts/headlines.py"
$H config set delivery.method email       # or discord / both
$H config set email.to "you@example.com"  # reuses the papers himalaya account; no second setup
$H config set email.from "you@example.com"
$H config set email.transport himalaya
$H sources sync-blogwatcher --dry-run     # feeds to add to headlines/state/blogwatcher.db
$H sources sync-blogwatcher
make status-headlines
```

Then ask Hermes to "set up the morning headlines" for the interview
(labs/models/products to prioritize or skip, topics such as open-weights,
econ or policy, source pruning, size and verbosity). For SMTP instead of
himalaya, set `smtp.*` in the headlines config and export
`MORNING_HEADLINES_SMTP_PASSWORD`.

Default sources that were unusable from a Raspberry Pi in Nov 2026 and are
left out: reddit (403), the GovAI feed (404), the Brookings AI feed (empty),
the X/Twitter API (needs a key), `lmarena.ai/leaderboard` (403; the Arena
blog `news.lmarena.ai` is used instead) and `z.ai/blog` (404; Z.ai's release
notes page is used). `x.ai/news` is included but marked low-confidence (it has
returned 403 to scripts).

### Cron jobs

The papers job is unchanged:

```bash
hermes cron create "0 7 * * *" "Run today's Morning Papers digest ..." \
  --name the-morning-papers --skill the-morning-papers \
  --workdir <repo> --deliver discord:<channel_id>
```

Headlines runs first, so papers can skip what headlines already covered:

```bash
hermes cron create "45 6 * * *" \
  "Run today's Morning Headlines digest. export MORNING_HEADLINES_HOME=<repo>/headlines; follow headlines/SKILL.md." \
  --name the-morning-headlines --skill the-morning-headlines \
  --workdir <repo> --deliver discord:<channel_id>
```

Or deliver `local` and post with a separate no-agent job that reads the cron
output and opens a thread titled with the first `1.` line under
`⭐ Top Stories` (the papers post script does the same with `Top Picks`).

### Blog watching (blogwatcher-cli)

Feed-backed blogs are tracked with [blogwatcher-cli](https://github.com/JulienTant/blogwatcher-cli)
so the daily run only surfaces posts that are *new* since yesterday, instead of
re-scraping every blog. Its SQLite DB lives at `state/blogwatcher.db` (headlines: `headlines/state/blogwatcher.db`; set
`BLOGWATCHER_DB` to point there); like the rest of `state/`, it is local and not committed. Sources with no discoverable RSS feed stay on
direct `web_extract` and are intentionally NOT tracked (a feedless source hangs
`scan`). Install:

```bash
curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_linux_amd64.tar.gz | tar xz -C ~/.local/bin blogwatcher-cli
```

### Discord delivery

Discord needs no script or credentials of its own: the Hermes cron job's final
response *is* the digest, and the Hermes gateway posts it to the job's
`--deliver` target, opening a thread you can reply in with feedback. Your Hermes
must have Discord connected. Create the job with the channel ID:

```bash
hermes cron create "0 7 * * *" "Run today's Morning Papers digest ..." \
  --name the-morning-papers --skill the-morning-papers \
  --workdir "$(pwd)" --deliver discord:<channel_id>
```

`scripts/render_discord.py` rewrites the digest for Discord (links without
preview cards, no horizontal rules) and checks it fits Hermes's per-response
limit of 8 Discord messages; the agent condenses the Discord copy if not.

### Email transport
- **himalaya** (recommended): configure the `himalaya` CLI once; `email.transport`
  defaults to `auto` and will use it.
- **SMTP**: set host/port/username in `config.json` and export the password:
  ```bash
  python3 scripts/papers.py config set smtp.host smtp.gmail.com
  python3 scripts/papers.py config set smtp.username you@gmail.com
  export MORNING_PAPERS_SMTP_PASSWORD='...'   # never commit this
  ```

Preview without sending:
```bash
uv run scripts/send_email.py --body-file digests/$(date +%F).md --dry-run
```

### Markdown rendering

The digest HTML is rendered with the [`markdown`](https://pypi.org/project/markdown/)
package (tables, fenced code, nested lists, footnotes). The script declares it
as a PEP 723 inline dependency, so it runs three ways with no venv to manage:

```bash
uv run scripts/send_email.py --body-file digests/$(date +%F).md   # uv provisions markdown
python3 scripts/send_email.py --body-file digests/$(date +%F).md   # uses markdown if installed
python3 scripts/send_email.py --body-file digests/$(date +%F).md   # bare stdlib fallback otherwise
```

If `markdown` is unavailable, a built-in stdlib fallback still renders
headings, lists, links, and inline formatting (tables degrade to plain text).

## Adjusting it over time

Everything is a CLI verb (Hermes maps natural language to these):

```bash
P="python3 scripts/papers.py"
$P interests add topics "diffusion language models"
$P feedback add "https://arxiv.org/abs/2401.01234" useful --note "great RL idea"
$P sources add "Some Lab" "https://lab.example/blog" --type blog
$P sources disable "Cohere"
$P config set digest.target_sections 4
$P config set digest.target_paper_count 10
$P config set evaluation.novelty_criteria "Be stricter: only paradigm shifts."
$P status
```

The headlines CLI has the same verbs (`python3 scripts/headlines.py ...`),
plus `seen add ... --tag model:x --alias arxiv:XXXX.XXXXX`. Both CLIs also have
`items group`, `decisions check`, `snapshot save|diff`, `sources enable` and
`sources sync-blogwatcher`.

See `SKILL.md` and `headlines/SKILL.md` for the full verb tables and the
daily run procedures.

## Tests

```bash
make test             # every suite: papers, core, urls, cross-dedup, back-compat
make test-headlines   # core + urls + cross-dedup
```

Stdlib only, temp homes only (they never touch repo state).
`tests/test_backcompat.py` builds a fixture with `papers.py` from commit
2583d84 and checks the new CLI and renderers give identical output.

## Privacy

Nothing personal is committed: `config/*.json` (email, interests, sources),
`state/` (feedback, run history, seen papers), and rendered digests are all
gitignored, and the same goes for `headlines/config/*.json`,
`headlines/state/*` and `headlines/digests/*` (only the `.gitkeep` files and
`headlines/digests/sample.md` are tracked), so the repo is safe to fork and
share. Check with `git status --ignored` and `git check-ignore -v <path>`. Secrets (SMTP password) live
in environment variables, never in the repo — `.gitignore` also excludes `.env`
and `config/secrets.json`.
