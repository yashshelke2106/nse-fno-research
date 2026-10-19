"""
Pre-registered hypothesis registry - append-only trial ledger.

WHY:
    Multiple-testing discipline requires knowing HOW MANY hypotheses were ever
    tried, not just how many appear in today's study. Every edge hunt must
    register BEFORE running; the stat gate reads trial_count() and widens its
    correction accordingly. An unregistered study is inadmissible.

    Append-only jsonl: records are never edited or deleted. Closing a
    hypothesis appends a closure record referencing the id.

Seed `_SEED` with any studies you ran BEFORE adopting the registry, so the
trial count is honest from day one - past trials spent alpha budget too.

RUN:
    python -m core.hypothesis_registry register "thesis" "test plan"
    python -m core.hypothesis_registry close H-001 REJECTED "reason, with the numbers"
    python -m core.hypothesis_registry list
    python -m core.hypothesis_registry count
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(_ROOT, "logs", "hypothesis_registry.jsonl")

# Studies run BEFORE the registry existed, as
#   (id, "YYYY-MM-DD", thesis, verdict, evidence)
# Each one consumed alpha budget, so the multiple-testing correction must count
# it. Empty in the public version.
_SEED: list = []


def _append(rec: Dict) -> None:
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    with open(REGISTRY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load() -> List[Dict]:
    if not os.path.exists(REGISTRY):
        return []
    out = []
    with open(REGISTRY, "r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _ensure_seeded() -> None:
    if os.path.exists(REGISTRY):
        return
    for hid, d, thesis, verdict, evidence in _SEED:
        _append({"type": "register", "id": hid, "ts": f"{d}T00:00:00",
                 "thesis": thesis, "test_plan": "(pre-registry)",
                 "seeded": True})
        _append({"type": "close", "id": hid, "ts": f"{d}T00:00:00",
                 "verdict": verdict, "evidence": evidence, "seeded": True})


def register(thesis: str, test_plan: str, universe: str = "FO_UNIVERSE",
             metric: str = "") -> str:
    """Pre-register a hypothesis BEFORE running any test. Returns new id.
    Refuses empty thesis/test_plan - a vague registration is no registration."""
    _ensure_seeded()
    thesis, test_plan = thesis.strip(), test_plan.strip()
    if not thesis or not test_plan:
        raise ValueError("thesis and test_plan are both required")
    n = sum(1 for r in _load() if r.get("type") == "register")
    hid = f"H-{n + 1:03d}"
    _append({"type": "register", "id": hid,
             "ts": datetime.now().isoformat(timespec="seconds"),
             "thesis": thesis, "test_plan": test_plan,
             "universe": universe, "metric": metric})
    return hid


def close(hid: str, verdict: str, evidence: str) -> None:
    """Append a closure record. verdict: REJECTED / PASS / CONDITIONAL-PASS /
    ABANDONED. Never edits the original registration."""
    _ensure_seeded()
    ids = {r["id"] for r in _load() if r.get("type") == "register"}
    if hid not in ids:
        raise ValueError(f"unknown hypothesis id {hid}")
    _append({"type": "close", "id": hid,
             "ts": datetime.now().isoformat(timespec="seconds"),
             "verdict": verdict.upper(), "evidence": evidence})


def trial_count() -> int:
    """Total hypotheses ever registered (open or closed). This is the number
    the stat gate uses to widen its multiple-testing correction."""
    _ensure_seeded()
    return sum(1 for r in _load() if r.get("type") == "register")


# Smoke-test registrations that should never appear beside real research. The
# log is append-only by design - a registration is never edited or deleted - so
# these are filtered at READ time rather than removed from the file.
_SCRATCH_THESES = ("test thesis",)


def _is_scratch(thesis: str) -> bool:
    t = str(thesis or "").strip().lower()
    return any(t.startswith(m) for m in _SCRATCH_THESES)


def status(include_scratch: bool = False) -> List[Dict]:
    """One row per hypothesis with latest verdict (None = still open).

    Scratch registrations ("test thesis xyz") are hidden unless asked for: they
    were rendering in the Verdict table next to real hunts, which makes the
    registry look careless in exactly the surface meant to enforce care.
    trial_count() still counts them - the multiple-testing bar must not fall
    because a row was hidden from a table.
    """
    _ensure_seeded()
    regs: Dict[str, Dict] = {}
    for r in _load():
        if r.get("type") == "register":
            regs[r["id"]] = {"id": r["id"], "ts": r["ts"],
                             "thesis": r["thesis"], "verdict": None}
        elif r.get("type") == "close" and r.get("id") in regs:
            regs[r["id"]]["verdict"] = r.get("verdict")
    rows = list(regs.values())
    if include_scratch:
        return rows
    return [r for r in rows if not _is_scratch(r.get("thesis"))]


def main(argv: List[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "register" and len(argv) >= 3:
        hid = register(argv[1], argv[2])
        print(f"registered {hid}  (trial #{trial_count()})")
        return 0
    if cmd == "close" and len(argv) >= 4:
        close(argv[1], argv[2], argv[3])
        print(f"closed {argv[1]} {argv[2].upper()}")
        return 0
    if cmd == "count":
        print(trial_count())
        return 0
    if cmd == "list":
        rows = status()
        print(f"{'id':6s} {'verdict':17s} thesis")
        print("-" * 70)
        for r in rows:
            print(f"{r['id']:6s} {str(r['verdict'] or 'OPEN'):17s} {r['thesis'][:48]}")
        print(f"\ntotal trials: {len(rows)}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
