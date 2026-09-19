#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT_REL = Path("app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic")
PRO = ROOT_REL / "ProComic.kt"
BROWSER = ROOT_REL / "ProComicBrowserReader.kt"

BROWSER_SOURCE = r'''package eu.kanade.tachiyomi.extension.ar.procomic

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONTokener
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

data class ProComicBrowserReaderResult(
    val imageUrls: List<String>,
    val contractText: String,
    val blockedReason: String?,
    val finalUrl: String?,
)

object ProComicBrowserReader {

    private const val TIMEOUT_SECONDS = 30L
    private const val POLL_MS = 600L

    private fun resolveContext(): Context? = ProComic.applicationContext ?: runCatching {
        val activityThreadClass = Class.forName("android.app.ActivityThread")
        val method = activityThreadClass.getMethod("currentApplication")
        method.invoke(null) as? Context
    }.getOrNull()

    private val hosts = setOf(
        "app.procomic.pro", "app.procomic.net",
        "cdn1.procomic.pro", "cdn2.procomic.pro", "cdn3.procomic.pro", "cdn4.procomic.pro",
        "cdn1.procomic.net", "cdn2.procomic.net", "cdn3.procomic.net", "cdn4.procomic.net",
        "img1.procomic.pro", "img2.procomic.pro", "img3.procomic.pro", "img4.procomic.pro",
        "img1.procomic.net", "img2.procomic.net", "img3.procomic.net", "img4.procomic.net",
    )

    private val imageExtensions = setOf("avif", "webp", "jpg", "jpeg", "png")

    @SuppressLint("SetJavaScriptEnabled")
    fun load(url: String, requiredImageCount: Int): ProComicBrowserReaderResult {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "ProComicBrowserReader.load must not run on the main thread"
        }

        val application = resolveContext() ?: return ProComicBrowserReaderResult(emptyList(), "", "No Android application context available")
        val latch = CountDownLatch(1)
        val result = AtomicReference<ProComicBrowserReaderResult?>()
        val finished = AtomicBoolean(false)

        Handler(Looper.getMainLooper()).post {
            val webView = WebView(application)
            val handler = Handler(Looper.getMainLooper())

            fun finish(value: ProComicBrowserReaderResult) {
                if (!finished.compareAndSet(false, true)) return
                result.set(value)
                webView.stopLoading()
                webView.destroy()
                latch.countDown()
            }

            fun inspect() {
                if (finished.get()) return

                val script = """
                    (() => {
                      const urls = [];
                      const add = (value) => {
                        if (!value || typeof value !== "string") return;
                        try {
                          const u = new URL(value, location.href);
                          const host = u.hostname.toLowerCase();
                          const path = u.pathname.toLowerCase();
                          const ext = path.substring(path.lastIndexOf(".") + 1);
                          const hosts = ["app.procomic.pro","app.procomic.net",
                            "cdn1.procomic.pro","cdn2.procomic.pro","cdn3.procomic.pro","cdn4.procomic.pro",
                            "cdn1.procomic.net","cdn2.procomic.net","cdn3.procomic.net","cdn4.procomic.net",
                            "img1.procomic.pro","img2.procomic.pro","img3.procomic.pro","img4.procomic.pro",
                            "img1.procomic.net","img2.procomic.net","img3.procomic.net","img4.procomic.net"];
                          const exts = ["avif","webp","jpg","jpeg","png"];
                          const chapterMedia =
                            path.includes("/chapters/") ||
                            /^\/\d+\/\d+\//.test(path) ||
                            path.startsWith("/i/");
                          if (
                            u.protocol === "https:" &&
                            hosts.includes(host) &&
                            exts.includes(ext) &&
                            chapterMedia
                          ) {
                            urls.push(u.href);
                          }
                        } catch (_) {}
                      };
                      document.querySelectorAll("img").forEach((img) => {
                        add(img.currentSrc);
                        add(img.src);
                        add(img.getAttribute("data-src"));
                        add(img.getAttribute("data-lazy-src"));
                      });
                      performance.getEntriesByType("resource").forEach((entry) => add(entry.name));
                      const scripts = Array.from(document.scripts)
                        .map((s) => s.textContent || "")
                        .filter((s) => /appImages|deferredMedia|protectionV2|chapter-map-proxy-plan/.test(s))
                        .join("\\n");
                      const bodyText = (document.body && document.body.innerText || "").slice(0, 2000);
                      return JSON.stringify({
                        urls: Array.from(new Set(urls)),
                        scripts: scripts.slice(0, 900000),
                        bodyText: bodyText
                      });
                    })()
                """.trimIndent()

                webView.evaluateJavascript(script) { raw ->
                    if (finished.get()) return@evaluateJavascript

                    val json = runCatching {
                        val inner = JSONTokener(raw).nextValue() as? String
                            ?: return@runCatching null
                        org.json.JSONObject(inner)
                    }.getOrNull() ?: run {
                        handler.postDelayed(::inspect, POLL_MS)
                        return@evaluateJavascript
                    }

                    val urls = json.optJSONArray("urls")?.let { array ->
                        buildList {
                            for (i in 0 until array.length()) add(array.optString(i))
                        }
                    }.orEmpty().filter(::isAllowedImage).distinct()

                    val scripts = json.optString("scripts", "")
                    val bodyText = json.optString("bodyText", "")

                    val blocked = when {
                        bodyText.contains("Safe Browsing Required", true) ->
                            "Safe Browsing is still enabled for this WebView session"
                        bodyText.contains("Log in and disable Safe Browsing", true) ->
                            "The site still considers the WebView unauthenticated or Safe Browsing-enabled"
                        bodyText.contains("هذا المحتوى مقيد", true) ->
                            "The site still returned the restricted-content page"
                        else -> null
                    }

                    if (urls.size >= requiredImageCount) {
                        finish(ProComicBrowserReaderResult(urls, scripts, null, webView.url))
                    } else if (blocked != null) {
                        finish(ProComicBrowserReaderResult(urls, scripts, blocked, webView.url))
                    } else {
                        handler.postDelayed(::inspect, POLL_MS)
                    }
                }
            }

            webView.settings.javaScriptEnabled = true
            webView.settings.domStorageEnabled = true
            webView.settings.loadsImagesAutomatically = true
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)
            }
            CookieManager.getInstance().setAcceptCookie(true)
            runCatching { CookieManager.getInstance().flush() }

            webView.webChromeClient = WebChromeClient()
            webView.webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, finishedUrl: String?) {
                    inspect()
                }
            }

            val browserUrl = if (url.contains("://procomic.pro/")) {
                url.replace("://procomic.pro/", "://procomic.net/")
            } else {
                url
            }
            webView.loadUrl(browserUrl)
            handler.postDelayed(::inspect, 1000L)
            handler.postDelayed({
                if (!finished.get()) {
                    finish(
                        ProComicBrowserReaderResult(
                            emptyList(),
                            "",
                            "Authenticated WebView Reader timed out",
                            webView.url,
                        ),
                    )
                }
            }, TIMEOUT_SECONDS * 1000L)
        }

        if (!latch.await(TIMEOUT_SECONDS + 5L, TimeUnit.SECONDS)) {
            return ProComicBrowserReaderResult(emptyList(), "", "WebView execution timed out", null)
        }

        return result.get()
            ?: ProComicBrowserReaderResult(emptyList(), "", "WebView returned no Reader result", null)
    }

    private fun isAllowedImage(url: String): Boolean = runCatching {
        val uri = java.net.URI(url)
        uri.scheme.equals("https", true) &&
            uri.userInfo == null &&
            uri.query == null &&
            uri.fragment == null &&
            uri.host?.lowercase() in hosts &&
            uri.path?.substringAfterLast('.', "")?.lowercase() in imageExtensions
    }.getOrDefault(false)
}
'''

def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one anchor, found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")

def apply(root: Path) -> None:
    pro = root / PRO
    browser = root / BROWSER

    if not pro.is_file():
        raise SystemExit(f"missing {pro}")

    pro_text = pro.read_text(encoding="utf-8")
    reader_start = """        val (body, url, activeHost) = if (initialHasImages && !initialRedirectedAway) {"""
    if reader_start not in pro_text:
        raise SystemExit("upstream Reader selection anchor not found")

    reader_insertion = """        val browserResult = if (
            initialBody.contains("Safe Browsing Required", ignoreCase = true) ||
            initialBody.contains("Log in and disable Safe Browsing", ignoreCase = true) ||
            initialBody.contains("هذا المحتوى مقيد", ignoreCase = true)
        ) {
            runCatching {
                ProComicBrowserReader.load(initialUrl)
            }.onFailure {
                ProComicDiag.logException("PAGES", "authenticated browser Reader", initialUrl, it)
            }.getOrNull()
        } else {
            null
        }

        val browserBody = browserResult?.contractText?.takeIf { it.isNotBlank() }
        val (body, url, activeHost) = if (!browserBody.isNullOrBlank()) {
            val recoveredUrl = browserResult?.finalUrl ?: initialUrl
            val recoveredHost = runCatching { java.net.URI(recoveredUrl).host }
                .getOrNull()
                ?: initialHost
            ProComicDiag.logStage("PAGES", 15, "authenticated browser Reader contract recovered")
            Triple(browserBody, recoveredUrl, recoveredHost)
        } else     page_anchor = '''        val publicImages = ProComicUtils.extractPageImages(body, "PAGES", url)
        val pages = publicImages.mapIndexed { index, imageUrl ->
            Page(index, imageUrl = imageUrl)
        }.toMutableList()
'''
    page_replacement = '''        val initialImages = ProComicUtils.extractPageImages(body, "PAGES", url)

        val browserResult = if (
            body.contains("Safe Browsing Required", ignoreCase = true) ||
            body.contains("Log in and disable Safe Browsing", ignoreCase = true) ||
            body.contains("هذا المحتوى مقيد", ignoreCase = true)
        ) {
            runCatching {
                ProComicBrowserReader.load(url)
            }.onFailure {
                ProComicDiag.logException("PAGES", "authenticated browser Reader", url, it)
            }.getOrNull()
        } else {
            null
        }

        val browserImages = browserResult?.imageUrls.orEmpty()
            .filter(ProComicUtils::isAllowedPageImageUrl)
            .distinct()
        val browserContractImages = browserResult?.contractText
            ?.takeIf { it.isNotBlank() }
            ?.let {
                runCatching { ProComicUtils.extractPageImages(it, "BROWSER", url) }
                    .getOrDefault(emptyList())
            }
            .orEmpty()
        val recoveredImages = (browserImages + browserContractImages).distinct()

        if (recoveredImages.size > initialImages.size) {
            ProComicDiag.logStage(
                "PAGES",
                15,
                "authenticated browser Reader recovered " + recoveredImages.size + " images",
            )
            return recoveredImages.mapIndexed { index, imageUrl ->
                Page(index, imageUrl = imageUrl)
            }
        }

        browserResult?.blockedReason?.let {
            ProComicDiag.logStage("PAGES", 14, it)
        }

        val pages = initialImages.mapIndexed { index, imageUrl ->
            Page(index, imageUrl = imageUrl)
        }.toMutableList()
'''

    reader_request_old = '''        val readerHeaders = headersBuilder()
            .set("Referer", "https://procomic.pro/")
            .build()
        return GET(canonicalUrl, readerHeaders)
'''
    reader_request_new = '''        val readerHeaders = headersBuilder()
            .set("Referer", "https://procomic.pro/")
            .set("Cache-Control", "no-cache")
            .build()
        return GET(canonicalUrl, readerHeaders)
'''
    if reader_request_old in pro.read_text(encoding="utf-8"):
        replace_once(pro, reader_request_old, reader_request_new)

    browser.write_text(BROWSER_SOURCE, encoding="utf-8")
    pro_text = pro.read_text(encoding="utf-8")
    if "authenticated browser-backed Reader fallback" not in pro_text:
        pro_text = pro_text.replace(
            "Known limitations:\n",
            "Known limitations:\n   - Restricted/auth-required Reader responses are retried inside the persistent Mihon WebView profile; server-side entitlement remains authoritative.\n",
            1,
        )
    pro.write_text(pro_text, encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    apply(args.source_root.resolve())
    print("authenticated browser-backed Reader patch applied")

if __name__ == "__main__":
    main()
