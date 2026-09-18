#!/usr/bin/env python3
"""Regression contract for the 2026-09-18 Reader missing-appImages hotfix."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "reader-no-appimages-v2.patch"


def main() -> None:
    text = PATCH.read_text()
    required = [
        "hasReaderDeferredOrProtectedContract",
        "public appImages manifest absent; continuing with deferred/protected reader",
        'extractJsonArrayAfterKey(body, "images")',
        "fallback plain images[] found",
        "deferred/protected Reader contract detected",
        'filter { it.contains("/chapters/") }',
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise AssertionError(f"hotfix patch missing required fragments: {missing}")
    print("reader hotfix patch contract: PASS")


if __name__ == "__main__":
    main()
