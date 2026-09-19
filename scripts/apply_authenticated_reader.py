#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT_REL = Path("app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic")
PRO = ROOT_REL / "ProComic.kt"
BROWSER = ROOT_REL / "ProComicBrowserReader.kt"

BROWSER_SOURCE = r'''package eu.kanade.tachiyomi.extension.ar.procomic

import android.annotation.SuppressLint
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
import keiyoushi.utils.applicationContext

data class ProComicBrowserReaderResult(
    val imageUrls: List<String>,
    val contractText: String,
    val blockedReason: String?,
    val finalUrl: String?,
)

object ProComicBrowserReader {

    private const val TIMEOUT_SECONDS = 30L
    private const val POLL_MS = 600L

    private val hosts = setOf(
        "app.procomic.pro", "app.procomic.net",
        "cdn1.procomic.pro", "cdn2.procomic.pro", "cdn3.procomic.pro", "cdn4.procomic.pro",
        "cdn1.procomic.net", "cdn2.procomic.net", "cdn3.procomic.net", "cdn4.procomic.net",
        "img1.procomic.pro", "img2.procomic.pro", "img3.procomic.pro", "img4.procomic.pro",
        "img1.procomic.net", "img2.procomic.net", "img3.procomic.net", "img4.procomic.net",
    )

    private val imageExtensions = setOf("avif", "webp", "jpg", "jpeg", "png")

    @SuppressLint("SetJavaScriptEnabled")
    fun load(url: String, requiredImageCount: Int = 4): ProComicBrowserReaderResult {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "ProComicBrowserReader.load must not run on the main thread"
        }

        val application = applicationContext
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
                      const html = document.documentElement ? document.documentElement.outerHTML : "";
                      const contract = [scripts, html]
                        .filter(Boolean)
                        .join("\\n")
                        .slice(0, 1400000);
                      const bodyText = (document.body && document.body.innerText || "").slice(0, 2000);
                      return JSON.stringify({
                        urls: Array.from(new Set(urls)),
                        scripts: contract,
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

CLIENT_ANCHOR = '''        override val client: OkHttpClient = network.client.newBuilder()
        .addInterceptor(ProComicImageInterceptor(network.client))
        .build()
'''
CLIENT_REPLACEMENT = '''        override val client: OkHttpClient = network.client.newBuilder()
        .addInterceptor(ProComicImageInterceptor(network.client))
        .addInterceptor(ProComicWebViewImageInterceptor())
        .build()
'''

IMAGE_INTERCEPTOR_SOURCE = r'''package eu.kanade.tachiyomi.extension.ar.procomic

import android.annotation.SuppressLint
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class ProComicWebViewImageInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = chain.proceed(request)
        if (!ProComicUtils.isAllowedPageImageUrl(request.url.toString()) ||
            response.code !in setOf(401, 403)
        ) {
            return response
        }
        response.close()

        val fetched = ProComicWebViewFetcher.fetch(
            url = request.url.toString(),
            referer = request.header("Referer"),
        ) ?: throw IOException("ProComic Reader: authenticated WebView image fetch failed")

        if (fetched.status !in 200..299) {
            throw IOException("ProComic Reader: authenticated WebView image fetch failed (" + fetched.status + ")")
        }

        val bytes = Base64.decode(fetched.body, Base64.DEFAULT)
        val mediaType = fetched.contentType?.toMediaTypeOrNull()
        return Response.Builder()
            .request(request)
            .protocol(Protocol.HTTP_1_1)
            .code(200)
            .message("OK")
            .header("Content-Type", mediaType?.toString() ?: "image/*")
            .body(bytes.toResponseBody(mediaType))
            .build()
    }
}

internal data class ProComicWebViewFetchResult(
    val status: Int,
    val contentType: String?,
    val body: String,
)

internal object ProComicWebViewFetcher {
    private const val TIMEOUT_MS = 30_000L
    private val mainHandler = Handler(Looper.getMainLooper())

    private var webView: WebView? = null
    private val bridge = Bridge()

    fun fetch(url: String, referer: String?): ProComicWebViewFetchResult? {
        val latch = CountDownLatch(1)
        val result = AtomicReference<ProComicWebViewFetchResult?>()
        bridge.reset(latch, result)

        mainHandler.post {
            val parsed = runCatching { java.net.URI(url) }.getOrNull()
            val host = parsed?.host ?: return@post
            val scheme = parsed.scheme ?: "https"
            val origin = scheme + "://" + host + "/"
            val view = getWebView()

            view.webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, pageUrl: String?) {
                    val target = org.json.JSONObject.quote(url)
                    val ref = org.json.JSONObject.quote(referer ?: "")
                    val script =
                        "fetch(" + target + ",{" +
                            "method:'GET'," +
                            "credentials:'include'," +
                            "cache:'no-store'," +
                            "referrer:" + ref + "," +
                            "referrerPolicy:'strict-origin-when-cross-origin'" +
                        "}).then(async function(response) {" +
                            "var blob=await response.blob();" +
                            "var reader=new FileReader();" +
                            "reader.onloadend=function(){" +
                                "var value=String(reader.result||'');" +
                                "var comma=value.indexOf(',');" +
                                "window.ProComicWebViewBridge.finish(" +
                                    "response.status," +
                                    "(response.headers.get('content-type')||'')," +
                                    "(comma>=0?value.substring(comma+1):'')" +
                                ");" +
                            "};" +
                            "reader.readAsDataURL(blob);" +
                        "}).catch(function(error){" +
                            "window.ProComicWebViewBridge.fail(String(error));" +
                        "});"
                    view.evaluateJavascript(script, null)
                }
            }

            CookieManager.getInstance().setAcceptCookie(true)
            runCatching { CookieManager.getInstance().flush() }

            view.loadDataWithBaseURL(
                origin,
                "<html><head><meta charset='utf-8'></head><body></body></html>",
                "text/html",
                "UTF-8",
                null,
            )
        }

        return if (latch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)) result.get() else null
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun getWebView(): WebView {
        webView?.let { return it }

        return WebView(keiyoushi.utils.applicationContext).also { view ->
            view.settings.javaScriptEnabled = true
            view.settings.domStorageEnabled = true
            view.settings.databaseEnabled = true
            CookieManager.getInstance().setAcceptCookie(true)
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
                CookieManager.getInstance().setAcceptThirdPartyCookies(view, true)
            }
            view.addJavascriptInterface(
                object {
                    @JavascriptInterface
                    fun finish(status: Int, contentType: String, body: String) {
                        bridge.finish(status, contentType, body)
                    }

                    @JavascriptInterface
                    fun fail(message: String) {
                        bridge.fail(message)
                    }
                },
                "ProComicWebViewBridge",
            )
            webView = view
        }
    }

    private class Bridge {
        private var latch: CountDownLatch? = null
        private var result: AtomicReference<ProComicWebViewFetchResult?>? = null

        fun reset(
            latch: CountDownLatch,
            result: AtomicReference<ProComicWebViewFetchResult?>,
        ) {
            this.latch = latch
            this.result = result
        }

        fun finish(status: Int, contentType: String, body: String) {
            result?.set(
                ProComicWebViewFetchResult(status, contentType.ifBlank { null }, body),
            )
            latch?.countDown()
        }

        fun fail(message: String) {
            result?.set(ProComicWebViewFetchResult(599, "text/plain", message.take(512)))
            latch?.countDown()
        }
    }
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

    replace_once(pro, CLIENT_ANCHOR, CLIENT_REPLACEMENT)
    pro_text = pro.read_text(encoding="utf-8")
    reader_start = (
        "        val (body, url, activeHost) = if (initialHasImages && !initialRedirectedAway) {"
    )
    if reader_start not in pro_text:
        raise SystemExit("upstream Reader selection anchor not found")

    reader_insertion = (
        "        val browserResult = if (\n"
        "            (!initialHasImages && !initialRedirectedAway) ||\n"
        "            initialBody.contains(\"Safe Browsing Required\", ignoreCase = true) ||\n"
        "            initialBody.contains(\"Log in and disable Safe Browsing\", ignoreCase = true) ||\n"
        "            initialBody.contains(\"هذا المحتوى مقيد\", ignoreCase = true)\n"
        "        ) {\n"
        "            runCatching {\n"
        "                ProComicBrowserReader.load(initialUrl)\n"
        "            }.onFailure {\n"
        "                ProComicDiag.logException(\"PAGES\", \"authenticated browser Reader\", initialUrl, it)\n"
        "            }.getOrNull()\n"
        "        } else {\n"
        "            null\n"
        "        }\n"
        "\n"
        "        val browserBody = browserResult?.contractText?.takeIf { it.isNotBlank() }\n"
        "        val (body, url, activeHost) = if (!browserBody.isNullOrBlank()) {\n"
        "            val recoveredUrl = browserResult?.finalUrl ?: initialUrl\n"
        "            val recoveredHost = runCatching { java.net.URI(recoveredUrl).host }.getOrNull() ?: initialHost\n"
        "            ProComicDiag.logStage(\"PAGES\", 15, \"authenticated browser Reader contract recovered\")\n"
        "            Triple(browserBody, recoveredUrl, recoveredHost)\n"
        "        } else if (initialHasImages && !initialRedirectedAway) {"
    )
    pro_text = pro_text.replace(reader_start, reader_insertion, 1)
    pro.write_text(pro_text, encoding="utf-8")

    page_anchor = (
        "        val publicImages = ProComicUtils.extractPageImages(body, \"PAGES\", url)\n"
        "        val pages = publicImages.mapIndexed { index, imageUrl ->\n"
        "            Page(index, imageUrl = imageUrl)\n"
        "        }.toMutableList()\n"
    )
    page_replacement = page_anchor

    # Keep this patch source-only and idempotent.
    if page_anchor not in pro.read_text(encoding="utf-8"):
        raise SystemExit("upstream Reader page-list anchor not found")

    replace_once(pro, page_anchor, page_replacement)

    reader_request_old = (
        "        val readerHeaders = headersBuilder()\n"
        "            .set(\"Referer\", \"https://procomic.pro/\")\n"
        "            .build()\n"
        "        return GET(canonicalUrl, readerHeaders)\n"
    )
    reader_request_new = (
        "        val readerHeaders = headersBuilder()\n"
        "            .set(\"Referer\", \"https://procomic.pro/\")\n"
        "            .set(\"Cache-Control\", \"no-cache\")\n"
        "            .build()\n"
        "        return GET(canonicalUrl, readerHeaders)\n"
    )
    if reader_request_old in pro.read_text(encoding="utf-8"):
        replace_once(pro, reader_request_old, reader_request_new)

    browser.write_text(BROWSER_SOURCE, encoding="utf-8")
    image_interceptor = pro.parent / "ProComicWebViewImageInterceptor.kt"
    image_interceptor.write_text(IMAGE_INTERCEPTOR_SOURCE, encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    apply(args.source_root.resolve())
    print("authenticated browser Reader patch applied")

if __name__ == "__main__":
    main()
