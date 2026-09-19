#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def require(path: Path, text: str, description: str) -> None:
    if text not in path.read_text(encoding="utf-8"):
        raise AssertionError(f"{description}: missing {text!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    args = parser.parse_args()

    pro = (
        args.upstream
        / "app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic/ProComic.kt"
    )
    if not pro.is_file():
        raise AssertionError(f"missing generated ProComic.kt: {pro}")

    source = pro.read_text(encoding="utf-8")
    require(source, "val initialHasValidImages = runCatching", "valid-image probe")
    require(
        source,
        "ProComicUtils.extractPageImages(initialBody, diagUrl = initialUrl)",
        "parser probe",
    )
    require(source, "!initialHasValidImages ||", "browser fallback trigger")
    require(
        source,
        "else if (initialHasValidImages && !initialRedirectedAway)",
        "normal-body validity gate",
    )

    browser_block_start = source.index("val browserResult = if (")
    browser_block_end = source.index("\n        ) {", browser_block_start)
    browser_condition = source[browser_block_start:browser_block_end]
    if "!initialHasImages ||" in browser_condition:
        raise AssertionError("browser fallback still relies on the appImages marker alone")

    print("authenticated Reader valid-image probe checks: PASS")


if __name__ == "__main__":
    main()
