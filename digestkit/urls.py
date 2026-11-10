"""URL canonicalization and item keys.

Two key schemes live side by side:

* ``legacy_key()`` is the Morning Papers key, byte-for-byte what
  ``scripts/papers.py`` has always stored: ``arxiv:<id>``, ``url:<sha1(raw)[:16]>``
  (sha1 of the *raw* URL string) or ``id:<slug>``. The papers ledger keeps using
  it so existing keys still match.
* ``item_key()`` is the readable headlines key: ``arxiv:<id>``, ``hf:<org>/<name>``,
  ``gh:<owner>/<repo>``, ``hfspace:``/``hfdata:`` or ``url:<canonical url>``.

Cross-digest matching compares *match key sets* (``match_keys()``), which
contain both, so a papers record and a headlines record for the same thing meet
even though they were stored under different schemes.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from .store import slug

ARXIV_ID = r"[0-9]{4}\.[0-9]{4,5}"

# Query parameters that only track the click, never select content.
TRACKING_PARAMS = {
    "ref", "ref_src", "ref_url", "source", "fbclid", "gclid", "dclid",
    "msclkid", "yclid", "mc_cid", "mc_eid", "igshid", "si", "s", "smid", "cmpid",
    "_hsenc", "_hsmi", "mkt_tok", "spm", "share", "ncid", "guccounter",
    "guce_referrer", "guce_referrer_sig", "sr_share", "trk", "trkid",
    "amp", "taid", "_ga", "_gl", "oly_enc_id", "oly_anon_id", "vero_id", "wt.mc_id",
}
TRACKING_PREFIXES = ("utm_", "pk_", "hsa_", "__s", "at_")

HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")

# Redirectors whose target is a query parameter (unwrapped offline).
REDIRECT_PARAMS = {
    "news.google.com": ("url",),
    "google.com": ("url", "q"),
    "l.facebook.com": ("u",),
    "lm.facebook.com": ("u",),
    "out.reddit.com": ("url",),
    "href.li": (),
    "duckduckgo.com": ("uddg",),
    "l.messenger.com": ("u",),
    "linkedin.com": ("url",),
    "slack-redir.net": ("url",),
}


def legacy_key(raw: str) -> str:
    """The Morning Papers key (unchanged from scripts/papers.py at 2583d84)."""
    s = raw.strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})", s)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.match(r"^([0-9]{4}\.[0-9]{4,5})(v\d+)?$", s)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.match(r"^arxiv:([0-9]{4}\.[0-9]{4,5})", s, re.I)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.search(r"huggingface\.co/papers/([0-9]{4}\.[0-9]{4,5})", s)
    if m:
        return f"arxiv:{m.group(1)}"
    if s.startswith("http"):
        return "url:" + hashlib.sha1(s.encode()).hexdigest()[:16]
    return "id:" + slug(s)


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def _strip_host(host: str) -> str:
    host = host.lower().rstrip(".")
    changed = True
    while changed:
        changed = False
        for p in HOST_PREFIXES:
            if host.startswith(p) and host.count(".") >= 2:
                host = host[len(p):]
                changed = True
    return host


def _unwrap(parts) -> str | None:
    host = _strip_host(parts.hostname or "")
    for h, params in REDIRECT_PARAMS.items():
        if host == h or host.endswith("." + h):
            q = dict(parse_qsl(parts.query, keep_blank_values=True))
            for p in params:
                v = q.get(p, "")
                if is_url(v):
                    return v
    return None


def canonical_url(url: str) -> str:
    """Normalize a URL so trivially different links compare equal.

    https only, lowercase host without www./m./amp., no fragment, no tracking
    params, sorted query, no AMP suffix, no trailing slash (except the root),
    collapsed '//' in the path. Redirectors with the target in a query param
    (news.google.com ?url=, google.com/url?q=, ...) are unwrapped; t.co and
    other opaque shorteners can't be resolved offline and are left alone.
    """
    u = url.strip()
    if not is_url(u):
        if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(/|$)", u, re.I):
            u = "https://" + u
        else:
            return u
    for _ in range(3):
        parts = urlsplit(u)
        target = _unwrap(parts)
        if not target:
            break
        u = target
    parts = urlsplit(u)
    host = _strip_host(parts.hostname or "")
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    path = re.sub(r"/amp/?$", "", path) or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl in TRACKING_PARAMS or kl.startswith(TRACKING_PREFIXES):
            continue
        if kl == "output" and v.lower() == "amp":
            continue
        query.append((k, v))
    query.sort()
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def arxiv_id(raw: str) -> str | None:
    """arXiv id (no version) from an id, arxiv:/abs/pdf/html URL, HF papers or alphaxiv link."""
    s = unquote(raw.strip())
    m = re.match(rf"^(?:arxiv:)?({ARXIV_ID})(?:v\d+)?$", s, re.I)
    if m:
        return m.group(1)
    if not is_url(s):
        return None
    host = _strip_host(urlsplit(s).hostname or "")
    path = urlsplit(s).path
    if host in ("arxiv.org", "export.arxiv.org", "alphaxiv.org", "arxiv-sanity-lite.com",
                "scholar-inbox.com", "paperswithcode.com", "chatpaper.com"):
        m = re.search(rf"/(?:abs|pdf|html|overview|paper|papers)/({ARXIV_ID})(?:v\d+)?(?:\.pdf)?(?:/|$)", path)
        if m:
            return m.group(1)
    if host in ("huggingface.co", "hf.co"):
        m = re.match(rf"^/papers/({ARXIV_ID})(?:v\d+)?/?$", path)
        if m:
            return m.group(1)
    return None


_HF_RESERVED = {
    "papers", "blog", "spaces", "datasets", "docs", "models", "api", "learn",
    "posts", "collections", "organizations", "settings", "join", "login",
    "pricing", "enterprise", "tasks", "chat", "new", "inference-endpoints",
}
_GH_RESERVED = {
    "orgs", "topics", "features", "marketplace", "sponsors", "settings", "about",
    "pricing", "enterprise", "login", "join", "explore", "collections", "trending",
    "apps", "security", "customer-stories", "readme", "events", "site", "search",
}

_KEY_PREFIXES = ("arxiv:", "hf:", "gh:", "hfspace:", "hfdata:", "url:", "id:")


def item_key(raw: str) -> str:
    """Readable headlines key for a URL or id (see module docstring)."""
    s = raw.strip()
    a = arxiv_id(s)
    if a:
        return f"arxiv:{a}"
    low = s.lower()
    if low.startswith(_KEY_PREFIXES) and not is_url(s):
        prefix, _, rest = s.partition(":")
        prefix = prefix.lower()
        if prefix == "url":
            # url:<sha1> (legacy hash) stays as is; url:<link> is re-canonicalized
            return s if not is_url(rest) else "url:" + canonical_url(rest)
        if prefix in ("hf", "gh", "hfspace", "hfdata"):
            return f"{prefix}:{rest.strip('/').lower()}"
        return f"{prefix}:{rest}"
    if not is_url(s):
        return "id:" + slug(s)
    c = canonical_url(s)
    parts = urlsplit(c)
    host = parts.hostname or ""
    segs = [p for p in parts.path.split("/") if p]
    if host in ("huggingface.co", "hf.co") and segs:
        if segs[0] == "spaces" and len(segs) >= 3:
            return f"hfspace:{segs[1]}/{segs[2]}".lower()
        if segs[0] == "datasets" and len(segs) >= 3:
            return f"hfdata:{segs[1]}/{segs[2]}".lower()
        if segs[0] not in _HF_RESERVED and len(segs) >= 2 and (
            len(segs) == 2 or segs[2] in ("tree", "blob", "resolve", "discussions", "commits")
        ):
            return f"hf:{segs[0]}/{segs[1]}".lower()
    if host == "github.com" and len(segs) >= 2 and segs[0].lower() not in _GH_RESERVED:
        repo = segs[1][:-4] if segs[1].endswith(".git") else segs[1]
        if len(segs) == 2 or segs[2] in ("tree", "blob", "releases", "wiki"):
            return f"gh:{segs[0]}/{repo}".lower()
    return "url:" + c


def match_keys(raw: str) -> set[str]:
    """Every key under which `raw` could have been recorded by either digest."""
    s = raw.strip()
    if not s:
        return set()
    keys = {item_key(s), legacy_key(s)}
    return keys


def record_match_keys(key: str, rec: dict | None) -> set[str]:
    """Keys a stored ledger record answers to: its key, aliases, and its URL's keys."""
    keys = {key}
    rec = rec or {}
    for a in rec.get("aliases") or []:
        keys.add(a)
    url = rec.get("url") or ""
    if url:
        keys |= match_keys(url)
    if key.startswith("url:") and is_url(key[4:]):
        keys.add(item_key(key[4:]))
    return keys


def host_of(url: str) -> str:
    if not is_url(url):
        return ""
    return _strip_host(urlsplit(canonical_url(url)).hostname or "")


def normalize_tag(tag: str) -> str:
    """'Model: GPT 6.1' -> 'model:gpt-6.1'."""
    t = tag.strip().lower()
    if ":" in t:
        ns, _, val = t.partition(":")
        ns, val = ns.strip(), val.strip()
        val = re.sub(r"\s+", "-", val)
        return f"{re.sub(r'[^a-z0-9_-]', '', ns)}:{val}"
    return re.sub(r"\s+", "-", t)
