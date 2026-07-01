# the-morning-papers

A self-contained Hermes skill that emails you a daily TL;DR digest of genuinely
novel AI research — filtered to your interests, deduped against everything it
has raised before, and organized into themed sections.

Runs daily at **10:00 America/New_York** via a Hermes cron job.

## What it does

1. Pulls new arXiv papers, the Hugging Face trending feed, and a watch-list of
   lab blogs (OpenAI, Anthropic, DeepMind, Meta, Google, plus anything you add).
2. Keeps only novel, relevant work — filters out minor training-protocol tweaks,
   incremental benchmark bumps, and routine scaling reports.
3. Dedupes against every paper raised in prior runs.
4. Clusters survivors into sections and renders a clean Markdown digest.
5. Emails it to you.
6. On failure: waits 20 minutes and retries, up to 3 attempts per day.

## Layout

| Path | Purpose |
|------|---------|
| `SKILL.md` | The skill Hermes loads: run procedure, interview, feedback verbs. |
| `scripts/papers.py` | State/config manager — the deterministic backbone. |
| `scripts/send_email.py` | Digest email delivery (himalaya or SMTP). |
| `config/` | `config.json`, `interests.json`, `sources.json`. |
| `state/` | `seen_papers.json`, `runs.jsonl`, `feedback.jsonl`, `retry_state.json`. |
| `digests/` | `YYYY-MM-DD.md` — each rendered digest. |

## Setup

```bash
export MORNING_PAPERS_HOME=$(pwd)
python3 scripts/papers.py init
```

Then ask Hermes to "set up the morning papers" — it runs an interview for your
email address, topics/keywords, labs/authors, seed blog confirmation, digest
verbosity and cap size, and any extra instructions.

### Blog watching (blogwatcher-cli)

Feed-backed blogs are tracked with [blogwatcher-cli](https://github.com/JulienTant/blogwatcher-cli)
so the daily run only surfaces posts that are *new* since yesterday, instead of
re-scraping every blog. Its SQLite DB lives at `state/blogwatcher.db` (set
`BLOGWATCHER_DB` to point there). Sources with no discoverable RSS feed stay on
direct `web_extract` and are intentionally NOT tracked (a feedless source hangs
`scan`). Install:

```bash
curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_linux_amd64.tar.gz | tar xz -C ~/.local/bin blogwatcher-cli
```

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

See `SKILL.md` for the full verb table and the daily run procedure.

## Privacy

This repo holds your interests, feedback, and run history. Keep it private.
Secrets (SMTP password) live in environment variables, never in the repo —
`.gitignore` also excludes `.env` and `config/secrets.json`.
