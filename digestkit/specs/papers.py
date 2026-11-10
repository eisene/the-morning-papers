"""The Morning Papers: daily AI research digest.

Defaults, seed sources and the ledger layout are exactly those of
scripts/papers.py at 2583d84, so a live install keeps working with no
migration.
"""
from __future__ import annotations

from ..store import slug, today
from ..urls import legacy_key
from . import REPO_ROOT, DigestSpec, register


def default_config() -> dict:
    return {
        # How the digest reaches the reader. "email" sends via scripts/send_email.py;
        # "discord" makes the digest the Hermes cron job's final response, which the
        # gateway posts to the job's --deliver target (scripts/render_discord.py);
        # "both" does both. Discord needs no settings here: the target lives on the
        # cron job. Missing key = "email" (configs written before this existed).
        "delivery": {
            "method": "email",  # email | discord | both
        },
        "email": {
            "to": "",
            "from": "",
            "subject_template": "The Morning Papers — {date}",
            "style_instructions": (
                "TL;DR style. Lead with a one-line takeaway per paper, then 1-2 "
                "sentences on why it matters and what is novel. Group into clearly "
                "titled sections. Keep it skimmable; link every paper."
            ),
            "transport": "auto",  # auto | himalaya | smtp
        },
        "smtp": {
            "host": "",
            "port": 587,
            "username": "",
            "use_tls": True,
            "password_env": "MORNING_PAPERS_SMTP_PASSWORD",
        },
        "digest": {
            "target_sections": 5,
            "target_paper_count": 12,
            "verbosity": "medium",  # terse | medium | detailed
        },
        "evaluation": {
            "novelty_criteria": (
                "Prefer genuinely new ideas: new problem framings, architectures, "
                "training objectives, theoretical results, or surprising empirical "
                "findings. Down-rank minor tweaks to training protocols, incremental "
                "benchmark bumps, routine scaling reports, and dataset/leaderboard "
                "papers with no new idea."
            ),
            "usefulness_criteria": (
                "A paper is useful if it changes how the reader would think or build: "
                "actionable methods, strong evidence, or ideas that transfer."
            ),
            "organization": (
                "Cluster by theme, not by source. Put the most novel/important items "
                "first within each section."
            ),
        },
        "schedule": {"time": "07:00", "tz": "America/New_York"},
        "retry": {"max_attempts": 3, "wait_minutes": 20},
    }


def default_interests() -> dict:
    return {
        "topics": [],
        "keywords": [],
        "authors_prioritize": [],
        "authors_exclude": [],
        "labs_prioritize": [],
        "labs_exclude": [],
        "extra_instructions": "",
    }


# Seed sources: big-lab blogs + trending feeds. `feed` left blank means the
# agent should auto-discover it (blogwatcher / RSS) at run time.
SEED_SOURCES = [
    ("Hugging Face Papers", "https://huggingface.co/papers", "trending", ""),
    ("arXiv cs.LG (new)", "https://arxiv.org/list/cs.LG/recent", "arxiv", ""),
    ("arXiv cs.CL (new)", "https://arxiv.org/list/cs.CL/recent", "arxiv", ""),
    ("arXiv cs.AI (new)", "https://arxiv.org/list/cs.AI/recent", "arxiv", ""),
    ("OpenAI Blog", "https://openai.com/news/", "blog", ""),
    ("Anthropic Research", "https://www.anthropic.com/research", "blog", ""),
    ("Google DeepMind Blog", "https://deepmind.google/discover/blog/", "blog", ""),
    ("Google Research Blog", "https://research.google/blog/", "blog", ""),
    ("Meta AI Blog", "https://ai.meta.com/blog/", "blog", ""),
    ("Microsoft Research Blog", "https://www.microsoft.com/en-us/research/blog/", "blog", ""),
    ("BAIR Blog", "https://bair.berkeley.edu/blog/", "blog", "https://bair.berkeley.edu/blog/feed.xml"),
    ("Stanford AI Lab (SAIL)", "https://ai.stanford.edu/blog/", "blog", ""),
    ("Mistral AI News", "https://mistral.ai/news/", "blog", ""),
    ("Cohere Blog", "https://cohere.com/blog", "blog", ""),
    ("AI2 (Allen Institute) Blog", "https://allenai.org/blog", "blog", ""),
    ("Sebastian Raschka (Ahead of AI)", "https://magazine.sebastianraschka.com/", "blog", ""),
    ("Lilian Weng (Lil'Log)", "https://lilianweng.github.io/", "blog", "https://lilianweng.github.io/index.xml"),
]


def default_sources() -> dict:
    srcs = []
    for name, url, typ, feed in SEED_SOURCES:
        srcs.append(
            {
                "id": slug(name),
                "name": name,
                "url": url,
                "type": typ,  # blog | arxiv | trending | other
                "feed": feed,
                "priority": 1,
                "usefulness": 0,  # net signal from run outcomes / feedback
                "active": True,
                "notes": "",
                "added": today(),
            }
        )
    return {"sources": srcs}


SPEC = register(DigestSpec(
    name="papers",
    title="The Morning Papers",
    prog="papers.py",
    description=(
        "The Morning Papers — state & configuration manager.\n\n"
        "Deterministic backbone for the `the-morning-papers` Hermes skill. Every mutation\n"
        "the agent or user makes to interests, sources, feedback, dedup tracking, run\n"
        "history, retry state, and email/digest settings goes through this CLI so the\n"
        "skill never hand-edits JSON.\n\n"
        "Stdlib only. Data lives under the repo root; override with --home or\n"
        "MORNING_PAPERS_HOME."
    ),
    home_env="MORNING_PAPERS_HOME",
    default_home=lambda: REPO_ROOT,
    ledger_file="seen_papers.json",
    ledger_key="papers",
    noun="paper",
    default_config=default_config,
    default_interests=default_interests,
    default_sources=default_sources,
    interest_fields=frozenset({
        "topics", "keywords", "authors_prioritize", "authors_exclude",
        "labs_prioritize", "labs_exclude",
    }),
    source_types=("blog", "arxiv", "trending", "other"),
    default_source_type="blog",
    key_fn=legacy_key,
    subject_template="The Morning Papers — {date}",
    smtp_password_env="MORNING_PAPERS_SMTP_PASSWORD",
    peers=("headlines",),
))
