#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT_REL = Path("app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic")
PRO = ROOT_REL / "ProComic.kt"
BROWSER = ROOT_REL / "ProComicBrowserReader.kt"

BROWSER_SESSION_SOURCE = r'''package eu.kanade.tachiyomi.extension.ar.procomic

import android.annotation.SuppressLint
import android.os.Handler
import android.os.Looper
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.UserAgentMetadata
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import org.json.JSONTokener
import java.net.URI
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.locks.ReentrantLock

data class ProComicBrowserReaderResult(
    val contractText: String,
    val blockedReason: String?,
    val finalUrl: String?,
    val stateSummary: String,
)

internal data class ProComicBrowserFetchResult(
    val status: Int,
    val contentType: String?,
    val textBody: String?,
    val base64Body: String?,
)

internal object ProComicBrowserSession {
    private const val TIMEOUT_MS = 35_000L
    private const val FETCH_TIMEOUT_MS = 30_000L
    private const val POLL_MS = 400L
    private const val MAX_CONTRACT = 1_900_000

    private val lock = ReentrantLock()
    private val mainHandler = Handler(Looper.getMainLooper())

    private val pageHosts = setOf("procomic.pro", "procomic.net")
    private val mediaHosts = setOf(
        "app.procomic.pro", "app.procomic.net",
        "cdn1.procomic.pro", "cdn2.procomic.pro", "cdn3.procomic.pro", "cdn4.procomic.pro",
        "cdn1.procomic.net", "cdn2.procomic.net", "cdn3.procomic.net", "cdn4.procomic.net",
        "img1.procomic.pro", "img2.procomic.pro", "img3.procomic.pro", "img4.procomic.pro",
        "img1.procomic.net", "img2.procomic.net", "img3.procomic.net", "img4.procomic.net",
    )

    fun loadChapterContract(
        url: String,
        headers: Map<String, String> = emptyMap(),
    ): ProComicBrowserReaderResult? {
        require(Looper.myLooper() != Looper.getMainLooper())
        validatePageUrl(url)
        lock.lock()
        try {
            return loadChapterContractLocked(url, headers)
        } finally {
            lock.unlock()
        }
    }

    fun fetchText(
        url: String,
        referer: String?,
        accept: String = "application/json",
    ): ProComicBrowserFetchResult? = fetch(url, referer, accept, false)

    fun fetchBinary(
        url: String,
        referer: String?,
        accept: String = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    ): ProComicBrowserFetchResult? = fetch(url, referer, accept, true)

    private fun fetch(
        url: String,
        referer: String?,
        accept: String,
        binary: Boolean,
    ): ProComicBrowserFetchResult? {
        require(Looper.myLooper() != Looper.getMainLooper())
        validateFetchUrl(url)
        lock.lock()
        try {
            return fetchLocked(url, referer, accept, binary)
        } finally {
            lock.unlock()
        }
    }

    private fun validatePageUrl(url: String) {
        val uri = URI(url)
        require(uri.scheme.equals("https", true))
        require(uri.host?.lowercase() in pageHosts)
        require(uri.userInfo == null && uri.fragment == null)
    }

    private fun validateFetchUrl(url: String) {
        val uri = URI(url)
        val host = uri.host?.lowercase().orEmpty()
        require(uri.scheme.equals("https", true))
        require(host in pageHosts || host in mediaHosts)
        require(uri.userInfo == null && uri.fragment == null)
    }

    private fun loadChapterContractLocked(
        url: String,
        headers: Map<String, String>,
    ): ProComicBrowserReaderResult? {
        val latch = CountDownLatch(1)
        val result = AtomicReference<ProComicBrowserReaderResult?>()
        val completed = AtomicBoolean(false)

        mainHandler.post {
            val context = ProComic.applicationContext ?: run {
                latch.countDown()
                return@post
            }
            val webView = WebView(context)
            val handler = Handler(Looper.getMainLooper())
            val safeHeaders = headers.filterKeys {
                it.lowercase() !in setOf("host", "cookie", "content-length", "user-agent", "authorization")
            }.filterValues(String::isNotBlank)
            val requestUserAgent = headers.entries
                .firstOrNull { it.key.equals("User-Agent", true) }
                ?.value
                ?.takeIf(String::isNotBlank)

            fun finish(value: ProComicBrowserReaderResult) {
                if (!completed.compareAndSet(false, true)) return
                result.set(value)
                handler.removeCallbacksAndMessages(null)
                runCatching { CookieManager.getInstance().flush() }
                runCatching { webView.stopLoading() }
                runCatching { webView.destroy() }
                latch.countDown()
            }

            fun inspect() {
                if (completed.get()) return
                val js = """
                    (() => {
                      const markers = ["appImages","deferredMedia","protectionV2","chapter-map-proxy-plan"];
                      const body = (document.body && document.body.innerText || "").slice(0, 4000);
                      const html = document.documentElement ? (document.documentElement.outerHTML || "") : "";
                      const markerRe = /appImages|deferredMedia|protectionV2|chapter-map-proxy-plan/;
                      const scripts = Array.from(document.scripts)
                        .map(s => s.textContent || "")
                        .filter(s => markerRe.test(s))
                        .join("\\n");
                      const collect = value => {
                        const out = [];
                        if (!value) return out;
                        for (const marker of markers) {
                          let p = value.indexOf(marker), n = 0;
                          while (p >= 0 && n++ < 8) {
                            out.push(value.slice(Math.max(0, p - 280000), Math.min(value.length, p + 280000)));
                            p = value.indexOf(marker, p + marker.length);
                          }
                        }
                        return out;
                      };
                      let contract = scripts;
                      if (contract.length > MAX_CONTRACT) contract = collect(scripts).join("\\n");
                      if (contract.length < MAX_CONTRACT) {
                        contract += "\\n" + (html.length <= MAX_CONTRACT - contract.length ? html : collect(html).join("\\n"));
                      }
                      contract = contract.slice(0, MAX_CONTRACT);
                      let localSafe = null;
                      try {
                        for (let i = 0; i < localStorage.length; i++) {
                          const key = localStorage.key(i);
                          if (!key || !/safe.?brows/i.test(key)) continue;
                          const value = String(localStorage.getItem(key) || "").trim().toLowerCase();
                          if (["false","0","off","disabled","no"].includes(value)) { localSafe = false; break; }
                          if (["true","1","on","enabled","yes"].includes(value)) { localSafe = true; break; }
                        }
                      } catch (_) {}
                      let windowSafe = null;
                      try {
                        if (typeof window.__SAFE_BROWSING === "boolean") windowSafe = window.__SAFE_BROWSING;
                      } catch (_) {}
                      return JSON.stringify({
                        contract,
                        safe: /Safe Browsing Required|Log in and disable Safe Browsing|التصفح الآمن/i.test(body),
                        premium: /Premium chapter|Unlock now for|محتوى مميز|افتح الفصل الآن/i.test(body),
                        login: /please log in|you must log in|سجل الدخول لقراءة|تسجيل الدخول لقراءة|هذا المحتوى مقيد/i.test(body),
                        localSafe,
                        windowSafe,
                        ready: document.readyState === "complete"
                      });
                    })()
                """.trimIndent().replace("\${" + "MAX_CONTRACT}", MAX_CONTRACT.toString())

                webView.evaluateJavascript(js) { raw ->
                    if (completed.get()) return@evaluateJavascript
                    val json = runCatching {
                        val inner = JSONTokener(raw).nextValue() as? String ?: return@runCatching null
                        org.json.JSONObject(inner)
                    }.getOrNull()

                    if (json == null) {
                        handler.postDelayed(::inspect, POLL_MS)
                        return@evaluateJavascript
                    }

                    val blocked = when {
                        json.optBoolean("premium") ->
                            "Premium chapter is locked by the ProComic server"
                        json.optBoolean("safe") ->
                            "ProComic requires Safe Browsing to be disabled in the account settings"
                        json.optBoolean("login") ->
                            "ProComic returned an authenticated-reader/login gate"
                        else -> null
                    }

                    val contract = json.optString("contract", "")
                    if (contract.contains("appImages", true) ||
                        contract.contains("\\\"appImages\\\"", true) ||
                        blocked != null
                    ) {
                        val safeState = when {
                            !json.isNull("windowSafe") -> json.optBoolean("windowSafe")
                            !json.isNull("localSafe") -> json.optBoolean("localSafe")
                            else -> null
                        }
                        finish(
                            ProComicBrowserReaderResult(
                                contractText = contract,
                                blockedReason = blocked,
                                finalUrl = webView.url,
                                stateSummary = summarizeState(webView.url, safeState),
                            ),
                        )
                    } else {
                        handler.postDelayed(::inspect, POLL_MS)
                    }
                }
            }

            configureWebView(webView, requestUserAgent)
            webView.webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, finishedUrl: String?) {
                    inspect()
                }
            }
            webView.webChromeClient = WebChromeClient()
            webView.loadUrl(url, safeHeaders)
            handler.postDelayed(::inspect, 750L)
            handler.postDelayed({
                if (!completed.get()) {
                    finish(
                        ProComicBrowserReaderResult(
                            contractText = "",
                            blockedReason = "Authenticated Reader WebView timed out",
                            finalUrl = webView.url,
                            stateSummary = summarizeState(webView.url, null),
                        ),
                    )
                }
            }, TIMEOUT_MS)
        }

        return if (latch.await(TIMEOUT_MS + 5_000L, TimeUnit.MILLISECONDS)) result.get() else null
    }

    private fun fetchLocked(
        url: String,
        referer: String?,
        accept: String,
        binary: Boolean,
    ): ProComicBrowserFetchResult? {
        val latch = CountDownLatch(1)
        val result = AtomicReference<ProComicBrowserFetchResult?>()
        val completed = AtomicBoolean(false)

        mainHandler.post {
            val context = ProComic.applicationContext ?: run {
                latch.countDown()
                return@post
            }
            val view = WebView(context)
            val handler = Handler(Looper.getMainLooper())
            val parsed = URI(url)
            val origin = parsed.scheme + "://" + (parsed.rawAuthority ?: parsed.host) + "/"
            val target = org.json.JSONObject.quote(url)
            val ref = if (referer.isNullOrBlank()) "undefined" else org.json.JSONObject.quote(referer)
            val acceptJson = org.json.JSONObject.quote(accept)

            fun finish(value: ProComicBrowserFetchResult) {
                if (!completed.compareAndSet(false, true)) return
                result.set(value)
                handler.removeCallbacksAndMessages(null)
                runCatching { view.stopLoading() }
                runCatching { view.destroy() }
                latch.countDown()
            }

            val bridge = object {
                @JavascriptInterface
                fun text(status: Int, contentType: String, body: String) {
                    handler.post {
                        finish(ProComicBrowserFetchResult(status, contentType.ifBlank { null }, body, null))
                    }
                }

                @JavascriptInterface
                fun binary(status: Int, contentType: String, body: String) {
                    handler.post {
                        finish(ProComicBrowserFetchResult(status, contentType.ifBlank { null }, null, body))
                    }
                }

                @JavascriptInterface
                fun fail(message: String) {
                    handler.post {
                        finish(ProComicBrowserFetchResult(599, "text/plain", message.take(512), null))
                    }
                }
            }

            configureWebView(view, null)
            view.addJavascriptInterface(bridge, "ProComicBrowserBridge")
            view.webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, finishedUrl: String?) {
                    val body = if (binary) {
                        """
                        response.blob().then(function(blob) {
                          var r = new FileReader();
                          r.onloadend = function() {
                            var v = String(r.result || ""), c = v.indexOf(",");
                            window.ProComicBrowserBridge.binary(
                              response.status,
                              response.headers.get("content-type") || "",
                              c >= 0 ? v.substring(c + 1) : ""
                            );
                          };
                          r.readAsDataURL(blob);
                        })
                        """.trimIndent()
                    } else {
                        "response.text().then(function(t) { window.ProComicBrowserBridge.text(response.status, response.headers.get('content-type') || '', t); })"
                    }

                    val script =
                        "(async function(){try{const response=await fetch(" + target +
                            ",{method:'GET',credentials:'include',cache:'no-store',referrer:" + ref +
                            ",referrerPolicy:'strict-origin-when-cross-origin',headers:{'Accept':" + acceptJson +
                            ",'Accept-Language':'ar,en;q=0.9'}});" + body +
                            ".catch(function(e){window.ProComicBrowserBridge.fail(String(e));});}" +
                            "catch(e){window.ProComicBrowserBridge.fail(String(e));}})()"
                    view.evaluateJavascript(script, null)
                }
            }
            view.webChromeClient = WebChromeClient()
            view.loadDataWithBaseURL(
                origin,
                "<html><head><meta charset='utf-8'></head><body></body></html>",
                "text/html",
                "UTF-8",
                null,
            )
            handler.postDelayed({
                if (!completed.get()) finish(ProComicBrowserFetchResult(598, "text/plain", "Browser fetch timed out", null))
            }, FETCH_TIMEOUT_MS)
        }

        return if (latch.await(FETCH_TIMEOUT_MS + 5_000L, TimeUnit.MILLISECONDS)) result.get() else null
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView(view: WebView, userAgent: String?) {
        with(view.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            cacheMode = WebSettings.LOAD_DEFAULT
            useWideViewPort = true
            loadWithOverviewMode = true
            setSupportMultipleWindows(true)
        }
        CookieManager.getInstance().setAcceptCookie(true)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(view, true)
        }
        if (!userAgent.isNullOrBlank()) {
            view.settings.userAgentString = userAgent
            runCatching {
                if (WebViewFeature.isFeatureSupported(WebViewFeature.USER_AGENT_METADATA)) {
                    val match = Regex("""Chrome/(\d+)(\.[\d.]+)?""").find(userAgent)
                    if (match != null) {
                        val major = match.groupValues[1]
                        val full = major + match.groupValues[2].ifEmpty { ".0.0.0" }
                        val metadata = WebSettingsCompat.getUserAgentMetadata(view.settings)
                        val brands = metadata.brandVersionList.map {
                            val brand = if (it.brand == "Android WebView") "Google Chrome" else it.brand
                            UserAgentMetadata.BrandVersion.Builder()
                                .setBrand(brand)
                                .setMajorVersion(major)
                                .setFullVersion(full)
                                .build()
                        }
                        WebSettingsCompat.setUserAgentMetadata(
                            view.settings,
                            UserAgentMetadata.Builder(metadata)
                                .setBrandVersionList(brands)
                                .setFullVersion(full)
                                .build(),
                        )
                    }
                }
            }
        }
    }

    private fun summarizeState(url: String?, safeBrowsing: Boolean?): String {
        val cm = CookieManager.getInstance()
        val pro = cookieNames(cm.getCookie("https://procomic.pro/"))
        val net = cookieNames(cm.getCookie("https://procomic.net/"))
        fun authNames(items: List<String>) = items.filter {
            it.contains("session", true) || it.contains("auth", true) || it.contains("kratos", true)
        }.joinToString(",").ifBlank { "none" }
        return "finalUrl=" + (url ?: "null") +
            "; proSessionCookies=" + authNames(pro) +
            "; netSessionCookies=" + authNames(net) +
            "; safeBrowsingState=" + (safeBrowsing?.toString() ?: "unknown")
    }

    private fun cookieNames(raw: String?): List<String> = raw.orEmpty()
        .split(';')
        .mapNotNull { it.substringBefore('=').trim().takeIf(String::isNotBlank) }
        .distinct()
        .sorted()
}
'''CLIENT_ANCHOR = '''    override val client: OkHttpClient = network.client.newBuilder()
        .addInterceptor(ProComicImageInterceptor(network.client))
        .build()
'''
CLIENT_REPLACEMENT = '''    override val client: OkHttpClient = network.client.newBuilder()
        .addInterceptor(ProComicImageInterceptor(network.client))
        .addInterceptor(ProComicWebViewImageInterceptor())
        .build()
'''

IMAGE_INTERCEPTOR_SOURCE = r'''package eu.kanade.tachiyomi.extension.ar.procomic

import java.io.IOException
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody

class ProComicWebViewImageInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = chain.proceed(request)
        if (!ProComicUtils.isAllowedPageImageUrl(request.url.toString()) ||
            response.code !in setOf(401, 403)
        ) return response

        response.close()
        val fetched = ProComicBrowserSession.fetchBinary(
            request.url.toString(),
            request.header("Referer"),
        ) ?: throw IOException("ProComic Reader: authenticated WebView image fetch timed out")

        if (fetched.status !in 200..299 || fetched.base64Body.isNullOrBlank()) {
            throw IOException(
                "ProComic Reader: authenticated WebView image fetch failed (" +
                    fetched.status + ")",
            )
        }

        val bytes = try {
            android.util.Base64.decode(fetched.base64Body, android.util.Base64.DEFAULT)
        } catch (e: IllegalArgumentException) {
            throw IOException("ProComic Reader: WebView image response was not valid base64", e)
        }

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
'''
def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one anchor, found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")

def apply(root: Path) -> None:
    pro = root / PRO
    session = root / SESSION
    interceptor = root / IMAGE_INTERCEPTOR
    legacy_reader = root / LEGACY_READER
    build_gradle = root / BUILD_GRADLE

    if not pro.is_file() or not build_gradle.is_file():
        raise SystemExit("missing expected upstream files")

    replace_once(pro, CLIENT_ANCHOR, CLIENT_REPLACEMENT)

    pro_text = pro.read_text(encoding="utf-8")
    replace_once(pro, READER_FALLBACK_ANCHOR, READER_FALLBACK_REPLACEMENT)
    pro_text = replace_function(
        pro_text,
        DEFERRED_SIGNATURE,
        DEFERRED_SOURCE,
        "\n\n    // ---- Image URL ----",
    )

    reader_request_old = '''        val readerHeaders = headersBuilder()
            .set("Referer", "https://procomic.pro/")
            .build()
'''
    reader_request_new = '''        val readerHeaders = headersBuilder()
            .set("Referer", "https://procomic.pro/")
            .set("Cache-Control", "no-cache")
            .build()
'''
    if reader_request_old in pro_text:
        pro_text = pro_text.replace(reader_request_old, reader_request_new, 1)

    pro.write_text(pro_text, encoding="utf-8")
    session.write_text(BROWSER_SESSION_SOURCE, encoding="utf-8")
    interceptor.write_text(IMAGE_INTERCEPTOR_SOURCE, encoding="utf-8")

    if legacy_reader.exists():
        legacy_reader.unlink()

    gradle_text = build_gradle.read_text(encoding="utf-8")
    if "androidx.webkit:webkit:" not in gradle_text:
        replace_once(
            build_gradle,
            "dependencies {\n",
            'dependencies {\n    // Mihon provides AndroidX WebKit at runtime; compile against the same WebView API.\n    compileOnly("androidx.webkit:webkit:1.17.0")\n',
        )

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    apply(args.source_root.resolve())
    print("authenticated browser Reader patch applied")

if __name__ == "__main__":
    main()
