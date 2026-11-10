"""The Morning Headlines: daily AI news digest.

Model releases, benchmarks and leaderboards, product launches, economics /
policy / institute work and notable industry news, merged across sources so
each story appears once, with the primary source as its link.
"""
from __future__ import annotations

from urllib.parse import quote

from ..store import slug, today
from ..urls import item_key
from . import REPO_ROOT, DigestSpec, register

SECTIONS = [
    ("top-stories", "⭐ Top Stories"),
    ("model-releases", "Model releases"),
    ("benchmarks", "Benchmarks & leaderboards"),
    ("product-launches", "Product launches"),
    ("econ-policy", "Economics, policy & institutes"),
    ("industry", "Industry & business"),
    ("worth-reading", "Worth reading"),
    ("also-notable", "Also notable"),
]


def default_config() -> dict:
    return {
        # email | discord | both (see the papers config for what each means)
        "delivery": {"method": "email"},
        "email": {
            "to": "",
            "from": "",
            "subject_template": "The Morning Headlines — {date}",
            "style_instructions": (
                "One entry per story. Bold linked title to the primary source, then "
                "one or two sentences: what happened and why it matters. Add *Also:* "
                "links for other coverage. Skimmable; no hype words."
            ),
            "transport": "auto",  # auto | himalaya | smtp
        },
        "smtp": {
            "host": "",
            "port": 587,
            "username": "",
            "use_tls": True,
            "password_env": "MORNING_HEADLINES_SMTP_PASSWORD",
        },
        "digest": {
            "target_item_count": 15,
            "top_stories": 3,
            "max_age_hours": 36,
            "verbosity": "medium",  # terse | medium | detailed
        },
        "evaluation": {
            "importance_criteria": (
                "Lead with what changes the field or the market: frontier and notable "
                "open-weights model releases, new state of the art on a respected "
                "benchmark, launches people will use, large funding/M&A/policy moves, "
                "and serious economic or institutional analysis. Down-rank minor "
                "point releases, rumours, opinion without new information, and "
                "marketing posts."
            ),
            "primary_source_rule": (
                "Link the primary source (lab post, model card, docs, filing). Press and "
                "aggregators go in *Also:*. Never report an aggregator's claim without "
                "finding the primary source; if there is none, say so."
            ),
            "organization": (
                "Use the standard sections, skip empty ones, most important first within "
                "each section."
            ),
        },
        "schedule": {"time": "06:45", "tz": "America/New_York"},
        "retry": {"max_attempts": 3, "wait_minutes": 20},
    }


def default_interests() -> dict:
    return {
        "topics": [],
        "keywords": [],
        "labs_prioritize": [],
        "labs_exclude": [],
        "models_prioritize": [],
        "products_prioritize": [],
        "exclude_keywords": [],
        "extra_instructions": "",
    }


# abs:AI matters: many econ abstracts say only "AI" (e.g. arXiv:2611.05417
# "Organizing Intelligence", econ.TH, which the phrase-only query missed).
ARXIV_ECON_QUERY = (
    '(cat:econ.GN OR cat:econ.TH OR cat:econ.EM) AND (abs:AI OR abs:"artificial intelligence" '
    'OR abs:"language model" OR abs:"large language" OR abs:automation OR abs:AGI)'
)
ARXIV_ECON_URL = (
    "https://export.arxiv.org/api/query?search_query=" + quote(ARXIV_ECON_QUERY, safe="")
    + "&sortBy=submittedDate&sortOrder=descending&max_results=50"
)

# (name, url, type, feed, class, filter, notes)
SEED_SOURCES = [
    # aggregators / press
    ("smol.ai AI News", "https://news.smol.ai/", "aggregator", "", "aggregator", "",
     "Page source: daily issues with titles and dates (its RSS stalled in Sep 2026). "
     "Best recap of AI Twitter/X; always find the primary source for its claims. "
     "Redirected to https://latent.space/news/ on 2026-11-09."),
    ("Techmeme", "https://www.techmeme.com/", "aggregator", "https://www.techmeme.com/feed.xml",
     "aggregator", "AI only", ""),
    ("Hacker News Best", "https://news.ycombinator.com/best", "aggregator", "https://hnrss.org/best",
     "aggregator", "AI only", ""),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/", "aggregator",
     "https://techcrunch.com/category/artificial-intelligence/feed/", "press", "", ""),
    ("The Verge AI", "https://www.theverge.com/ai-artificial-intelligence", "aggregator",
     "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "press", "", ""),
    # institutes / economics / policy
    ("Google DeepMind Institute Essays", "https://institute.deepmind.com/essays/", "institute", "",
     "primary", "", "Page source: essay list with dates, no feed."),
    ("Epoch AI", "https://epochai.substack.com/", "institute", "https://epochai.substack.com/feed",
     "primary", "", ""),
    ("METR", "https://metr.org/", "institute", "https://metr.org/feed.xml", "primary", "", ""),
    ("AI Policy Perspectives", "https://www.aipolicyperspectives.com/", "institute",
     "https://www.aipolicyperspectives.com/feed", "primary", "", ""),
    ("NBER New Working Papers", "https://www.nber.org/papers", "institute",
     "https://www.nber.org/rss/new.xml", "primary", "AI only", ""),
    ("arXiv econ x AI", ARXIV_ECON_URL, "arxiv", "", "primary", "",
     "arXiv API query (econ.GN/TH/EM with AI terms). Rate-limited: one call per run, "
     "wait >=5 s before any retry; https://export.arxiv.org only."),
    ("Anthropic Institute", "https://www.anthropic.com/institute", "institute", "", "primary", "", ""),
    ("Anthropic Economic Index", "https://www.anthropic.com/economic-index", "institute", "",
     "primary", "", ""),
    # labs / releases
    ("Anthropic News", "https://www.anthropic.com/news", "lab", "", "primary", "", ""),
    ("OpenAI News", "https://openai.com/news/", "lab", "https://openai.com/news/rss.xml", "primary", "", ""),
    ("Google AI Blog", "https://blog.google/technology/ai/", "lab", "https://blog.google/technology/ai/rss/",
     "primary", "", ""),
    ("Google DeepMind Blog", "https://deepmind.google/discover/blog/", "lab",
     "https://deepmind.google/blog/rss.xml", "primary", "", ""),
    ("Meta AI Blog", "https://ai.meta.com/blog/", "lab", "", "primary", "", ""),
    ("Mistral AI News", "https://mistral.ai/news/", "lab", "https://mistral.ai/news/rss", "primary", "", ""),
    ("xAI News", "https://x.ai/news", "lab", "", "primary", "",
     "Low confidence: has returned 403 to scripted fetches; skip quietly if blocked."),
    ("DeepSeek News", "https://api-docs.deepseek.com/news/", "lab", "", "primary", "", ""),
    ("Qwen Blog", "https://qwenlm.github.io/blog/", "lab", "https://qwenlm.github.io/blog/index.xml",
     "primary", "", ""),
    ("Moonshot AI", "https://www.moonshot.ai/en", "lab", "", "primary", "", ""),
    ("Z.ai Release Notes", "https://docs.z.ai/release-notes/new-released", "release", "", "primary", "",
     "Dated list of new model releases (z.ai/blog is a 404)."),
    ("MiniMax News", "https://www.minimax.io/news", "lab", "", "primary", "", ""),
    ("NVIDIA Blog", "https://blogs.nvidia.com/", "lab", "https://blogs.nvidia.com/feed/", "primary",
     "AI only", ""),
    ("Apple Machine Learning Research", "https://machinelearning.apple.com/", "lab",
     "https://machinelearning.apple.com/rss.xml", "primary", "", ""),
    ("Together AI Blog", "https://www.together.ai/blog", "lab", "https://www.together.ai/blog/rss.xml",
     "primary", "", ""),
    ("AWS Machine Learning Blog", "https://aws.amazon.com/blogs/machine-learning/", "lab",
     "https://aws.amazon.com/blogs/machine-learning/feed/", "primary", "launches only", ""),
    ("GitHub Blog", "https://github.blog/", "lab", "https://github.blog/feed/", "primary", "AI only", ""),
    ("Hugging Face Blog", "https://huggingface.co/blog", "release", "https://huggingface.co/blog/feed.xml",
     "primary", "", ""),
    ("Hugging Face Trending Models", "https://huggingface.co/api/models?sort=trendingScore&limit=30",
     "api", "", "primary", "org releases only",
     "JSON (id, tags, createdAt, likes). Drop repos tagged uncensored/abliterated/heretic, gguf, "
     "base_model:finetune:* or base_model:quantized:* (re-uploads); keep org releases."),
    # leaderboards
    ("LMArena News", "https://news.lmarena.ai/", "leaderboard", "", "primary", "",
     "Arena blog: leaderboard and index announcements (lmarena.ai/leaderboard is 403 to "
     "scripts). Redirected to https://arena.ai/blog on 2026-11-09."),
    ("Artificial Analysis", "https://artificialanalysis.ai/", "leaderboard", "", "primary", "",
     "Page source; optional snapshot diffing."),
    # newsletters ("Worth reading")
    ("Simon Willison", "https://simonwillison.net/", "newsletter",
     "https://simonwillison.net/atom/everything/", "aggregator", "", ""),
    ("Import AI", "https://importai.substack.com/", "newsletter", "https://importai.substack.com/feed",
     "aggregator", "", ""),
    ("Interconnects", "https://www.interconnects.ai/", "newsletter", "https://www.interconnects.ai/feed",
     "aggregator", "", ""),
    ("Don't Worry About the Vase (Zvi)", "https://thezvi.substack.com/", "newsletter",
     "https://thezvi.substack.com/feed", "aggregator", "", ""),
    ("Latent Space", "https://www.latent.space/", "newsletter", "https://www.latent.space/feed",
     "aggregator", "", ""),
    ("SemiAnalysis", "https://newsletter.semianalysis.com/", "newsletter",
     "https://newsletter.semianalysis.com/feed", "aggregator", "", ""),
    ("Understanding AI", "https://www.understandingai.org/", "newsletter",
     "https://www.understandingai.org/feed", "aggregator", "", ""),
    ("Exponential View", "https://www.exponentialview.co/", "newsletter",
     "https://www.exponentialview.co/feed", "aggregator", "", ""),
    ("One Useful Thing", "https://www.oneusefulthing.org/", "newsletter",
     "https://www.oneusefulthing.org/feed", "aggregator", "", ""),
    ("AI Snake Oil", "https://www.aisnakeoil.com/", "newsletter", "https://www.aisnakeoil.com/feed",
     "aggregator", "", ""),
    ("Dwarkesh Podcast", "https://www.dwarkesh.com/", "newsletter", "https://www.dwarkesh.com/feed",
     "aggregator", "", ""),
]


def default_sources() -> dict:
    srcs = []
    for name, url, typ, feed, cls, flt, notes in SEED_SOURCES:
        srcs.append({
            "id": slug(name),
            "name": name,
            "url": url,
            "type": typ,
            "feed": feed,
            "priority": 1,
            "usefulness": 0,
            "active": True,
            "notes": notes,
            "added": today(),
            "filter": flt,
            "class": cls,
        })
    return {"sources": srcs}


# Host suffix -> source class for picking a group's primary link (ranking in
# digestkit.items.CLASS_RANK). Longest suffix wins; unknown hosts fall back to
# the source's class/type, else "other".
DOMAIN_CLASSES = {
    # labs / vendors / institutes (primary sources)
    "openai.com": "primary", "anthropic.com": "primary", "deepmind.google": "primary",
    "blog.google": "primary", "ai.google.dev": "primary", "research.google": "primary",
    "ai.meta.com": "primary", "about.fb.com": "primary", "mistral.ai": "primary",
    "x.ai": "primary", "deepseek.com": "primary", "qwenlm.github.io": "primary",
    "qwen.ai": "primary", "moonshot.ai": "primary", "moonshot.cn": "primary", "z.ai": "primary",
    "minimax.io": "primary", "blogs.nvidia.com": "primary", "nvidianews.nvidia.com": "primary",
    "machinelearning.apple.com": "primary", "apple.com": "primary", "together.ai": "primary",
    "aws.amazon.com": "primary", "github.blog": "primary", "huggingface.co": "primary",
    "microsoft.com": "primary", "blogs.microsoft.com": "primary", "cohere.com": "primary",
    "allenai.org": "primary", "institute.deepmind.com": "primary", "epoch.ai": "primary",
    "epochai.substack.com": "primary", "metr.org": "primary", "lmarena.ai": "primary",
    "artificialanalysis.ai": "primary", "arena.ai": "primary", "nber.org": "primary", "sec.gov": "primary",
    "whitehouse.gov": "primary", "europa.eu": "primary", "gov.uk": "primary",
    "aipolicyperspectives.com": "primary", "ai.gov": "primary",
    # docs / repos / papers
    "github.com": "docs", "arxiv.org": "docs", "docs.z.ai": "docs",
    "api-docs.deepseek.com": "primary", "platform.openai.com": "docs",
    "docs.anthropic.com": "docs", "docs.claude.com": "docs", "docs.mistral.ai": "docs",
    "readthedocs.io": "docs",
    # press
    "techcrunch.com": "press", "theverge.com": "press", "reuters.com": "press",
    "bloomberg.com": "press", "ft.com": "press", "wsj.com": "press", "nytimes.com": "press",
    "cnbc.com": "press", "axios.com": "press", "theinformation.com": "press",
    "wired.com": "press", "arstechnica.com": "press", "venturebeat.com": "press",
    "semafor.com": "press", "washingtonpost.com": "press", "economist.com": "press",
    "businessinsider.com": "press", "fortune.com": "press", "forbes.com": "press",
    "theregister.com": "press", "technologyreview.com": "press", "apnews.com": "press",
    "scmp.com": "press", "zdnet.com": "press", "engadget.com": "press",
    # aggregators / social / newsletters
    "techmeme.com": "aggregator", "news.smol.ai": "aggregator", "smol.ai": "aggregator",
    "hnrss.org": "aggregator", "news.ycombinator.com": "aggregator", "reddit.com": "aggregator",
    "x.com": "aggregator", "twitter.com": "aggregator", "t.co": "aggregator",
    "substack.com": "aggregator", "simonwillison.net": "aggregator",
    "interconnects.ai": "aggregator", "latent.space": "aggregator",
    "understandingai.org": "aggregator", "exponentialview.co": "aggregator",
    "oneusefulthing.org": "aggregator", "aisnakeoil.com": "aggregator",
    "dwarkesh.com": "aggregator", "normaltech.ai": "aggregator", "newsletter.semianalysis.com": "aggregator",
    "importai.substack.com": "aggregator", "thezvi.substack.com": "aggregator",
    "youtube.com": "aggregator", "linkedin.com": "aggregator",
}


SPEC = register(DigestSpec(
    name="headlines",
    title="The Morning Headlines",
    prog="headlines.py",
    description=(
        "The Morning Headlines — state & configuration manager.\n\n"
        "Deterministic backbone for the `the-morning-headlines` Hermes skill: config,\n"
        "interests, sources, the seen-items ledger (with cross-digest dedup against\n"
        "The Morning Papers), item grouping, decision-log checks, feedback, runs and\n"
        "retries. All state access goes through this CLI.\n\n"
        "Stdlib only. Home: --home > MORNING_HEADLINES_HOME > <repo>/headlines."
    ),
    home_env="MORNING_HEADLINES_HOME",
    default_home=lambda: REPO_ROOT / "headlines",
    ledger_file="seen_items.json",
    ledger_key="items",
    noun="item",
    default_config=default_config,
    default_interests=default_interests,
    default_sources=default_sources,
    interest_fields=frozenset({
        "topics", "keywords", "labs_prioritize", "labs_exclude",
        "models_prioritize", "products_prioritize", "exclude_keywords",
    }),
    source_types=("aggregator", "institute", "lab", "release", "leaderboard",
                  "newsletter", "arxiv", "api", "other"),
    default_source_type="lab",
    key_fn=item_key,
    subject_template="The Morning Headlines — {date}",
    smtp_password_env="MORNING_HEADLINES_SMTP_PASSWORD",
    peers=("papers",),
    source_extra_fields=("filter", "class"),
    own_match_index=True,
    domain_classes=DOMAIN_CLASSES,
))
