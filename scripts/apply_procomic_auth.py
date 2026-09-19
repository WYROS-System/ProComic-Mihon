#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

AUTH_FILE = r'''package eu.kanade.tachiyomi.extension.ar.procomic

import android.webkit.CookieManager
import okhttp3.HttpUrl
import okhttp3.Request

object ProComicWebViewAuth {

    private const val SESSION_COOKIE = "ory_kratos_session"

    fun isLoggedIn(): Boolean {
        val manager = runCatching { CookieManager.getInstance() }.getOrNull() ?: return false
        runCatching { manager.flush() }
        return LOGIN_URLS.any { url ->
            manager.getCookie(url).orEmpty().split(';').any { raw ->
                val cookie = raw.trimStart()
                cookie.startsWith("$SESSION_COOKIE=") &&
                    cookie.substringAfter('=').isNotBlank()
            }
        }
    }

    fun addCookies(builder: Request.Builder): Request.Builder {
        val request = builder.build()
        val manager = runCatching { CookieManager.getInstance() }.getOrNull() ?: return builder
        runCatching { manager.flush() }
        val webViewCookies = manager.getCookie(request.url.toString()).orEmpty()
        if (webViewCookies.isBlank()) return builder

        val merged = mergeCookieHeaders(
            request.header("Cookie").orEmpty(),
            webViewCookies,
        )
        return builder.header("Cookie", merged)
    }

    private fun mergeCookieHeaders(existing: String, webView: String): String {
        val values = linkedMapOf<String, String>()
        listOf(existing, webView).forEach { header ->
            header.split(';').forEach { part ->
                val separator = part.indexOf('=')
                if (separator <= 0) return@forEach
                val name = part.substring(0, separator).trim()
                val value = part.substring(separator + 1).trim()
                if (name.isNotEmpty()) values[name] = value
            }
        }
        return values.entries.joinToString("; ") { (name, value) -> "$name=$value" }
    }

    private val LOGIN_URLS = listOf(
        "https://procomic.net/",
        "https://app.procomic.net/",
        "https://procomic.pro/",
        "https://app.procomic.pro/",
    )
}
'''

def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: source anchor count != 1")
    path.write_text(text.replace(old, new), encoding="utf-8")

def apply(root: Path) -> None:
    base = root / "app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic"
    pro = base / "ProComic.kt"
    interceptor = base / "ProComicImageInterceptor.kt"
    if not pro.is_file() or not interceptor.is_file():
        raise SystemExit("expected ProComic source files are missing")

    text = pro.read_text(encoding="utf-8")

    login_old = '''    private fun isLoggedIn(): Boolean {
        val cookies = android.webkit.CookieManager.getInstance().getCookie(baseUrl) ?: return false
        return cookies.contains("ory_kratos_session=")
    }
'''
    if login_old in text:
        text = text.replace(login_old, '    private fun isLoggedIn(): Boolean = ProComicWebViewAuth.isLoggedIn()\n', 1)
        pro.write_text(text, encoding="utf-8")

    pro_text = pro.read_text(encoding="utf-8")
    interceptor_old = '''private class ProComicWebViewCookieInterceptor : Interceptor {

    private val allowedHosts = setOf(
        "procomic.pro",
        "procomic.net",
        "app.procomic.pro",
        "app.procomic.net",
        "cdn1.procomic.pro",
        "cdn2.procomic.pro",
        "cdn3.procomic.pro",
        "cdn4.procomic.pro",
        "cdn1.procomic.net",
        "cdn2.procomic.net",
        "cdn3.procomic.net",
        "cdn4.procomic.net",
    )

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        if (request.url.host.lowercase() !in allowedHosts) {
            return chain.proceed(request)
        }

        val webViewCookies = runCatching {
            android.webkit.CookieManager.getInstance().getCookie(request.url.toString())
        }.getOrNull().orEmpty()

        if (webViewCookies.isBlank()) {
            return chain.proceed(request)
        }

        val mergedCookies = mergeCookieHeaders(
            request.header("Cookie").orEmpty(),
            webViewCookies,
        )
        return chain.proceed(
            request.newBuilder()
                .header("Cookie", mergedCookies)
                .build(),
        )
    }

    private fun mergeCookieHeaders(existing: String, webView: String): String {
        val values = linkedMapOf<String, String>()
        listOf(existing, webView).forEach { header ->
            header.split(';').forEach { part ->
                val separator = part.indexOf('=')
                if (separator <= 0) return@forEach
                val name = part.substring(0, separator).trim()
                val value = part.substring(separator + 1).trim()
                if (name.isNotEmpty()) values[name] = value
            }
        }
        return values.entries.joinToString("; ") { (name, value) -> "$name=$value" }
    }
}

'''
    interceptor_new = '''private class ProComicWebViewCookieInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        return chain.proceed(
            ProComicWebViewAuth.addCookies(chain.request().newBuilder()).build(),
        )
    }
}

'''
    if interceptor_old in pro_text:
        replace_once(pro, interceptor_old, interceptor_new)

    pro_text = pro.read_text(encoding="utf-8")
    reader_old = '''        val readerHeaders = headersBuilder()
            .set("Referer", "https://procomic.pro/")
            .build()
        return GET(canonicalUrl, readerHeaders)
'''
    reader_new = '''        val readerHeaders = headersBuilder()
            .set("Referer", "https://procomic.pro/")
            .set("Cache-Control", "no-cache")
            .build()
        return GET(canonicalUrl, readerHeaders)
'''
    if reader_old in pro_text:
        replace_once(pro, reader_old, reader_new)

    map_old = '''            val request = pageRequest.newBuilder()
                .url("https://$host/chapter-map-proxy-plan/${payload.chapterId}")
                .header("Accept", "application/json")
                .header("Content-Type", "application/json")
                .header("Referer", "https://$host/")
                .post(body)
                .build()
'''
    map_new = '''            val request = ProComicWebViewAuth.addCookies(
                pageRequest.newBuilder()
                    .url("https://" + host + "/chapter-map-proxy-plan/" + payload.chapterId)
                    .header("Accept", "application/json")
                    .header("Content-Type", "application/json")
                    .header("Referer", "https://" + host + "/")
                    .post(body),
            ).build()
'''
    replace_once(interceptor, map_old, map_new)

    tile_old = '''                val tileRequest = pageRequest.newBuilder()
                    .url(pieceUrl)
                    .header("Accept", "image/avif,image/webp,image/*,*/*;q=0.8")
                    .header("Referer", tileReferer)
                    .build()
'''
    tile_new = '''                val tileRequest = ProComicWebViewAuth.addCookies(
                    pageRequest.newBuilder()
                        .url(pieceUrl)
                        .header("Accept", "image/avif,image/webp,image/*,*/*;q=0.8")
                        .header("Referer", tileReferer),
                ).build()
'''
    replace_once(interceptor, tile_old, tile_new)

    auth.write_text(AUTH_FILE, encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    apply(args.source_root.resolve())
    print("ProComic authenticated WebView bridge applied.")

if __name__ == "__main__":
    main()
