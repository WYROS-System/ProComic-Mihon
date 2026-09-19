#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def require(path: Path, text: str, description: str) -> None:
    if text not in path.read_text(encoding="utf-8"):
        raise AssertionError(f"{description}: missing {text!r}")


def forbid(path: Path, text: str, description: str) -> None:
    if text in path.read_text(encoding="utf-8"):
        raise AssertionError(f"{description}: forbidden text found: {text!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    args = parser.parse_args()

    root = args.upstream
    source = root / "app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic"
    pro = source / "ProComic.kt"
    session = source / "ProComicBrowserSession.kt"
    interceptor = source / "ProComicWebViewImageInterceptor.kt"
    build = root / "app/build.gradle.kts"
    fixtures_path = root / "testdata/reader/reader_contract_fixtures.json"

    for path in (pro, session, interceptor, build, fixtures_path):
        if not path.is_file():
            raise AssertionError(f"expected generated/upstream file is missing: {path}")

    require(session, "WebView(context)", "browser session")
    require(session, "domStorageEnabled = true", "browser session")
    require(session, "CookieManager.getInstance()", "browser session cookie bridge")
    require(session, "localStorage", "Safe Browsing storage inspection")
    require(session, 'key === "safe_browsing"', "Safe Browsing cookie inspection")
    require(session, "hasOrySession", "Ory session state detection")
    require(session, "__SAFE_BROWSING", "Safe Browsing runtime state inspection")
    require(session, "credentials:'include'", "browser fetch credentials")
    require(session, "loadDataWithBaseURL", "same-origin browser fetch")
    require(session, "ReentrantLock()", "serialized WebView access")
    require(session, "WebViewFeature.USER_AGENT_METADATA", "Mihon-compatible UA metadata")

    forbid(
        session,
        'replace("://procomic.pro/", "://procomic.net/")',
        "browser navigation must not force a cross-origin domain rewrite",
    )
    forbid(session, "private var webView: WebView?", "shared mutable WebView singleton")
    forbid(session, "setCookie(", "fake/manual auth cookie injection")
    forbid(session, "document.cookie =", "fake/manual auth cookie injection")
    forbid(session, "safeBrowsingEnabled = false", "Safe Browsing bypass")
    forbid(session, "entitlement", "entitlement bypass")
    forbid(session, "unlockChapter", "premium unlock injection")
    forbid(session, "purchaseChapter", "premium purchase injection")
    forbid(session, "coins:0", "premium purchase injection")

    require(interceptor, "response.code !in setOf(401, 403)", "image fallback scope")
    require(interceptor, "fetchBinary", "image browser fallback")
    require(interceptor, "fetchJsonPost", "protected map browser fallback")
    require(interceptor, "chapter-map-proxy-plan", "protected map endpoint handling")
    require(interceptor, "isAllowedProtectedTileUrl", "protected tile handling")
    forbid(interceptor, "private var webView", "image interceptor race-prone WebView singleton")

    pro_text = pro.read_text(encoding="utf-8")
    require(pro, "ProComicBrowserSession.loadChapterContract", "authenticated page fallback")
    require(pro, "Preference(screen.context)", "ProComic login preference")
    require(pro, "تسجيل الدخول إلى ProComic", "ProComic login entry")
    require(pro, "eu.kanade.tachiyomi.ui.webview.WebViewActivity", "Mihon WebView login activity")
    require(pro, "https://procomic.pro/ar", "login uses Reader origin")
    require(pro, "newIntent", "Mihon WebView intent helper")
    require(pro, "val initialHasValidImages = runCatching", "decoded-image validity probe")
    require(pro, "!initialHasValidImages ||", "browser fallback uses decoded-image validity")
    require(pro, "initialHasValidImages && !initialRedirectedAway", "normal Reader body uses decoded-image validity")
    if "!initialHasImages ||" in pro_text:
        raise AssertionError("browser fallback still uses the appImages marker alone")
    if "initialHasImages && !initialRedirectedAway" in pro_text:
        raise AssertionError("normal Reader branch still uses the appImages marker alone")
    require(pro, "browserNetworkClient", "browser-aware OkHttp client")
    require(pro, "ProComicImageInterceptor(browserNetworkClient)", "protected Reader client propagation")
    require(pro, "Triple(browserBody, recoveredUrl, recoveredHost)", "browser contract branch")
    if pro_text.count("val (body, url, activeHost) =") != 1:
        raise AssertionError("Reader body decision branch must exist exactly once")
    if pro_text.count("ProComicBrowserSession.loadChapterContract") != 1:
        raise AssertionError("authenticated page fallback call must exist exactly once")
    require(pro, "Cache-Control", "reader cache control")
    require(pro, "ProComicBrowserSession.fetchText", "authenticated deferred-media fallback")
    require(pro, "ProComicWebViewImageInterceptor()", "authenticated image interceptor")
    require(pro, "Safe Browsing Required", "Safe Browsing gate classification")
    require(session, "Premium chapter is locked by the ProComic server", "premium gate classification")
    require(pro, "Cache-Control", "reader cache control")
    forbid(pro, "requiredImageCount", "image-count success heuristic")

    require(build, 'compileOnly("androidx.webkit:webkit:1.17.0")', "AndroidX WebKit compile dependency")

    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    expected = {
        "multi_page_manifest",
        "safe_browsing_required",
        "missing_manifest",
        "escaped_rsc_manifest",
        "premium_locked",
        "live_escaped_rsc_with_trailing_object",
    }
    if not expected.issubset(fixtures):
        missing = sorted(expected.difference(fixtures))
        raise AssertionError(f"reader fixtures missing: {missing}")

    safe = fixtures["safe_browsing_required"]
    safe_blob = json.dumps(safe, ensure_ascii=False)
    assert "Safe Browsing Required" in safe_blob
    assert "Log in and disable Safe Browsing" in safe_blob

    premium = fixtures["premium_locked"]
    premium_blob = json.dumps(premium, ensure_ascii=False)
    assert "Premium chapter" in premium_blob
    assert "Unlock now for just 5 coins" in premium_blob

    for marker in (
        "appImages",
        "deferredMedia",
        "protectionV2",
        "chapter-map-proxy-plan",
    ):
        require(session, marker, f"Reader contract marker {marker}")

    print("authenticated Reader static/contract checks: PASS")


if __name__ == "__main__":
    main()
