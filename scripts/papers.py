#!/usr/bin/env python3
"""The Morning Papers — state & configuration manager.

Deterministic backbone for the `the-morning-papers` Hermes skill. Every mutation
the agent or user makes to interests, sources, feedback, dedup tracking, run
history, retry state, and email/digest settings goes through this CLI so the
skill never hand-edits JSON.

Stdlib only. Data lives under the repo root (config/, state/, digests/);
override it with --home or MORNING_PAPERS_HOME. The CLI is built by
digestkit.core from the papers spec (digestkit/specs/papers.py).

Run `papers.py --help` or `papers.py <group> --help` for usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digestkit import core  # noqa: E402
from digestkit.specs.papers import SPEC  # noqa: E402


def main(argv=None):
    return core.main(SPEC, argv)


if __name__ == "__main__":
    sys.exit(main())
