#!/usr/bin/env python3
"""Regression checks for the Reader missing-appImages hotfix."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "apply_reader_hotfix.py"


def main() -> None:
    text = PATCHER.read_text(encoding="utf-8")
    required = [
        'val publicImages = try {',
        "hasReaderDeferredOrProtectedContract",
        "public appImages manifest absent; continuing with deferred/protected reader",
        'extractJsonArrayAfterKey(body, "images")',
        "fallback plain images[] found",
        'filter { it.contains("/chapters/") }',
        "no public image manifest; deferred/protected Reader contract detected",
        "expected exactly one source anchor",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise AssertionError(f"missing hotfix implementation fragments: {missing}")
    print("reader hotfix implementation contract: PASS")


if __name__ == "__main__":
    main()
