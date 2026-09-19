#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def require(path: Path, text: str, description: str) -> None:
    source = path.read_text(encoding="utf-8")
    if text not in source:
        raise AssertionError(f"{description}: missing {text!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--komikku", type=Path, required=True)
    args = parser.parse_args()

    root = args.komikku
    loader = root / "app/src/main/java/eu/kanade/tachiyomi/extension/util/ExtensionLoader.kt"
    webview = root / "app/src/main/java/eu/kanade/tachiyomi/ui/webview/WebViewActivity.kt"
    manifest = root / "app/src/main/AndroidManifest.xml"

    for path in (loader, webview, manifest):
        if not path.is_file():
            raise AssertionError(f"Komikku compatibility file missing: {path}")

    # Komikku's current ExtensionLoader accepts the same 1.6 extension-lib API
    # used by the generated ProComic extension.
    require(
        loader,
        "private val SUPPORTED_LIB_VERSIONS = listOf(1.4, 1.6)",
        "Komikku extension-lib compatibility",
    )
    require(
        loader,
        "ChildFirstPathClassLoader(appInfo.sourceDir, null, context.classLoader)",
        "Komikku extension classloader",
    )

    # Komikku retains Mihon's WebViewActivity entry point in the same package and
    # the same intent extra names used by the compatibility-safe login launcher.
    require(webview, "class WebViewActivity : BaseActivity()", "Komikku WebView activity")
    require(webview, 'private const val URL_KEY = "url_key"', "Komikku WebView URL key")
    require(webview, 'private const val SOURCE_KEY = "source_key"', "Komikku WebView source key")
    require(webview, 'private const val TITLE_KEY = "title_key"', "Komikku WebView title key")

    require(
        manifest,
        'android:name=".ui.webview.WebViewActivity"',
        "Komikku WebView activity manifest registration",
    )

    print("Komikku compatibility checks: PASS")


if __name__ == "__main__":
    main()
