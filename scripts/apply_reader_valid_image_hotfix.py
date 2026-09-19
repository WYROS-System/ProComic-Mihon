#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

PRO_REL = Path(
    "app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic/ProComic.kt",
)

PROBE_RE = re.compile(
    r'(?m)^        val initialHasImages =.*\n'
    r'^        val initialRedirectedAway =.*\n\n'
    r'(?=        val browserResult = if \()'
)

PROBE_REPLACEMENT = """        val initialHasImages = initialBody.contains("appImages") || initialBody.contains("\\\\\"appImages\\\\\"")
        val initialRedirectedAway = !response.request.url.encodedPath.contains("/chapter/")
        // The marker alone is not sufficient: a challenge/error document can contain
        // the appImages marker while yielding zero valid page URLs. Probe the real parser
        // before deciding that the normal OkHttp response is usable.
        val initialHasValidImages = runCatching {
            ProComicUtils.extractPageImages(initialBody, diagUrl = initialUrl)
        }.getOrNull()?.isNotEmpty() == true

        val browserResult = if (
"""

BODY_OLD = "        } else if (initialHasImages && !initialRedirectedAway) {"
BODY_NEW = "        } else if (initialHasValidImages && !initialRedirectedAway) {"


def replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{description}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def apply(root: Path) -> None:
    path = root / PRO_REL
    if not path.is_file():
        raise SystemExit(f"missing expected ProComic.kt: {path}")

    source = path.read_text(encoding="utf-8")
    source, count = PROBE_RE.subn(PROBE_REPLACEMENT, source, count=1)
    if count != 1:
        raise SystemExit(f"valid-image probe anchor: expected exactly one match, found {count}")

    source = replace_once(
        source,
        "            !initialHasImages ||",
        "            !initialHasValidImages ||",
        "browser fallback validity condition",
    )

    source = replace_once(
        source,
        BODY_OLD,
        BODY_NEW,
        "valid-image body branch",
    )
    path.write_text(source, encoding="utf-8")
    print("authenticated Reader valid-image probe hotfix applied")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    apply(args.source_root.resolve())


if __name__ == "__main__":
    main()
