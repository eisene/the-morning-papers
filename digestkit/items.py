"""Group headline candidates that describe the same story.

Deterministic part only: candidates that share an item key (after URL
canonicalization) or a `model:`/`product:` tag are merged; the group's primary
link is the best-ranked source class (lab/vendor or model card, then docs/repo,
then press, then other, then aggregators/newsletters). Ranking stories and
writing them up is the agent's job.
"""
from __future__ import annotations

from .urls import host_of, item_key, match_keys, normalize_tag

ENTITY_NAMESPACES = ("model:", "product:")

CLASS_RANK = {"primary": 0, "docs": 1, "press": 2, "other": 3, "aggregator": 4}
# Source `type` -> class, used when the URL's host isn't in the domain table.
TYPE_CLASS = {
    "lab": "primary", "release": "primary", "institute": "primary", "leaderboard": "primary",
    "api": "primary", "arxiv": "docs", "aggregator": "aggregator", "newsletter": "aggregator",
    "blog": "primary", "trending": "aggregator",
}


def domain_class(url: str, table: dict) -> str | None:
    host = host_of(url)
    if not host:
        return None
    best, best_len = None, -1
    for suffix, cls in table.items():
        if host == suffix or host.endswith("." + suffix):
            if len(suffix) > best_len:
                best, best_len = cls, len(suffix)
    if best is None and host.startswith(("docs.", "developer.", "developers.")):
        return "docs"
    return best


def classify(cand: dict, table: dict, sources: list[dict]) -> tuple[str, str]:
    """(class, why) for one candidate."""
    if cand.get("class") in CLASS_RANK:
        return cand["class"], "candidate"
    url = cand.get("url") or ""
    key = item_key(url) if url else ""
    if key.startswith("hf:"):
        return "primary", "model card"
    if key.startswith("gh:"):
        return "docs", "repo"
    dc = domain_class(url, table)
    if dc:
        return dc, "domain"
    src = _find_source(sources, cand.get("source") or "")
    if src:
        cls = src.get("class") or TYPE_CLASS.get(src.get("type", ""), "")
        if cls in CLASS_RANK:
            return cls, "source"
    return "other", "default"


def _find_source(sources, query):
    if not query:
        return None
    q = query.lower()
    for s in sources:
        if s.get("id") == query or s.get("name", "").lower() == q:
            return s
    return None


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def group(cands: list[dict], table: dict, sources: list[dict], lookup) -> list[dict]:
    """Merge candidates into story groups.

    `lookup(keys, tags)` returns a list of hits
    `{"digest","key","record","via","own": bool}` from the ledgers.
    """
    norm = []
    for c in cands:
        if isinstance(c, str):
            c = {"url": c}
        c = dict(c)
        url = (c.get("url") or c.get("id") or "").strip()
        c["url"] = url
        tags = sorted({normalize_tag(t) for t in (c.get("tags") or []) if str(t).strip()})
        c["tags"] = tags
        c["key"] = item_key(url) if url else ""
        c["_keys"] = match_keys(url) if url else set()
        cls, why = classify(c, table, sources)
        c["class"] = cls
        c["class_from"] = why
        norm.append(c)

    uf = _UF(len(norm))
    owner: dict[str, int] = {}
    for i, c in enumerate(norm):
        ents = [t for t in c["tags"] if t.startswith(ENTITY_NAMESPACES)]
        for k in list(c["_keys"]) + ents:
            if k in owner:
                uf.union(owner[k], i)
            else:
                owner[k] = i

    buckets: dict[int, list[int]] = {}
    for i in range(len(norm)):
        buckets.setdefault(uf.find(i), []).append(i)

    groups = []
    for n, (_, idxs) in enumerate(sorted(buckets.items(), key=lambda kv: kv[0]), 1):
        members = [norm[i] for i in idxs]
        ranked = sorted(range(len(members)),
                        key=lambda j: (CLASS_RANK.get(members[j]["class"], 9), j))
        primary = members[ranked[0]]
        also_urls, also = set(), []
        for j in ranked[1:]:
            m = members[j]
            if m["key"] == primary["key"] or m["key"] in also_urls:
                continue  # same link twice: keep one
            also_urls.add(m["key"])
            also.append(_public(m))
        keys = sorted({k for m in members for k in m["_keys"]} | {m["key"] for m in members if m["key"]})
        member_keys = sorted({m["key"] for m in members if m["key"]})
        tags = sorted({t for m in members for t in m["tags"]})
        hits = lookup(set(keys), [t for t in tags if t.startswith(ENTITY_NAMESPACES)])
        own = [h for h in hits if h["own"]]
        peer = [h for h in hits if not h["own"]]
        dates = sorted(h["record"].get("first_raised", "") for h in hits if h["record"].get("first_raised"))
        groups.append({
            "group": n,
            "primary": _public(primary),
            "also": also,
            "member_keys": member_keys,
            "keys": keys,
            "tags": tags,
            "size": len(members),
            "seen": bool(own),
            "peer_seen": [_hit(h) for h in peer],
            "covered": bool(hits),
            "covered_on": dates[0] if dates else None,
            "covered_by": [_hit(h) for h in hits],
        })
    return groups


def _public(c: dict) -> dict:
    return {k: v for k, v in c.items() if not k.startswith("_")}


def _hit(h: dict) -> dict:
    rec = h["record"]
    return {
        "digest": h["digest"],
        "key": h["key"],
        "via": h["via"],
        "first_raised": rec.get("first_raised"),
        "title": rec.get("title", ""),
    }
