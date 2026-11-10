"""Digest specs: everything that differs between the digests.

A `DigestSpec` names the digest, says where its home is, which ledger file it
keeps, what its defaults and source types are and how it keys items. The CLI in
`digestkit.core` is built from a spec; `get(name)` returns a registered one.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class DigestSpec:
    name: str                       # "papers" | "headlines"
    title: str                      # "The Morning Papers"
    prog: str                       # argparse prog, e.g. "papers.py"
    description: str                # --help text
    home_env: str                   # MORNING_PAPERS_HOME
    default_home: Callable[[], Path]
    ledger_file: str                # file name under state/
    ledger_key: str                 # top-level key in the ledger JSON
    noun: str                       # "paper" | "item": JSON field names
    default_config: Callable[[], dict]
    default_interests: Callable[[], dict]
    default_sources: Callable[[], dict]
    interest_fields: frozenset
    source_types: tuple
    default_source_type: str
    key_fn: Callable[[str], str]
    subject_template: str
    smtp_password_env: str
    peers: tuple = ()
    # headlines-only extras
    source_extra_fields: tuple = ()        # e.g. ("filter", "class")
    own_match_index: bool = False          # match own ledger via aliases/urls too
    domain_classes: dict = field(default_factory=dict)  # host suffix -> class
    near_miss_headings: tuple = ("didn't quite make the cut", "near-miss", "near miss",
                                 "also notable", "housekeeping")

    def home(self, override: str | os.PathLike | None = None) -> Path:
        if override:
            return Path(override)
        env = os.environ.get(self.home_env)
        if env:
            return Path(env)
        return self.default_home()

    @property
    def ledger_path_rel(self) -> str:
        return f"state/{self.ledger_file}"


_REGISTRY: dict[str, DigestSpec] = {}


def register(spec: DigestSpec) -> DigestSpec:
    _REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> DigestSpec:
    from . import headlines, papers  # noqa: F401  (registers both)
    if name not in _REGISTRY:
        raise KeyError(f"unknown digest '{name}'; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def names() -> list[str]:
    get("papers")
    return sorted(_REGISTRY)
