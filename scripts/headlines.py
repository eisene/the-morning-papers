#!/usr/bin/env python3
"""The Morning Headlines — state & configuration manager.

Deterministic backbone for the `the-morning-headlines` Hermes skill
(headlines/SKILL.md): config, interests, sources, the seen-items ledger with
cross-digest dedup against The Morning Papers, `items group`, `decisions check`,
snapshots, feedback, runs and retries.

Stdlib only. Home: --home > MORNING_HEADLINES_HOME > <repo>/headlines. The CLI
is built by digestkit.core from digestkit/specs/headlines.py.

Run `headlines.py --help` or `headlines.py <group> --help` for usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digestkit import core  # noqa: E402
from digestkit.specs.headlines import SPEC  # noqa: E402


def main(argv=None):
    return core.main(SPEC, argv)


if __name__ == "__main__":
    sys.exit(main())
