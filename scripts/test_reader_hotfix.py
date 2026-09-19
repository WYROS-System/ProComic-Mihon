#!/usr/bin/env python3
"""Validate the maintained Reader/auth hotfix scripts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
reader = ROOT / "scripts" / "apply_reader_hotfix.py"
auth = ROOT / "scripts" / "apply_procomic_auth.py"


def main() -> None:
    reader_text = reader.read_text(encoding="utf-8")
    auth_text = auth.read_text(encoding="utf-8")

    required_reader = [
        "hasReaderDeferredOrProtectedContract",
        'extractJsonArrayAfterKey(body, "images")',
        "directCdnUrls",
    ]
    required_auth = [
        "CookieManager",
        "ory_kratos_session",
        "fun isLoggedIn(): Boolean",
        "fun addCookies",
        "Cache-Control",
        "ProComicWebViewAuth.addCookies",
    ]

    missing = [x for x in required_reader if x not in reader_text]
    missing += [x for x in required_auth if x not in auth_text]
    if missing:
        raise AssertionError(f"missing hotfix contract fragments: {missing}")

    print("reader/auth hotfix contract: PASS")


if __name__ == "__main__":
    main()
