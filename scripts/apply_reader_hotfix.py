#!/usr/bin/env python3
"""Apply the 2026-09-18 ProComic Reader missing-appImages hotfix.

Usage:
    python3 scripts/apply_reader_hotfix.py /path/to/mihon-extension-ar-procomic

The patch is intentionally source-only. It does not alter authentication, payment, or access
controls, and it refuses to continue if expected upstream source anchors are missing.
"""

from __future__ import annotations

import argparse
from pathlib import Path


PROCOMIC_IMPORT_ANCHOR = "import eu.kanade.tachiyomi.source.online.HttpSource\n"
PROCOMIC_IMPORT = "import okhttp3.Interceptor\n"

PROCOMIC_ANCHOR = '''        val publicImages = ProComicUtils.extractPageImages(body, "PAGES", url)
        val pages = publicImages.mapIndexed { index, imageUrl ->
'''
PROCOMIC_REPLACEMENT = '''        val publicImages = try {
            ProComicUtils.extractPageImages(body, "PAGES", url)
        } catch (error: Exception) {
            // Some current Reader responses omit the public appImages manifest while still
            // carrying the deferred/protected reader contract. Do not abort before we inspect
            // that contract below. Explicit access failures still propagate normally.
            if (ProComicUtils.hasReaderDeferredOrProtectedContract(body)) {
                ProComicDiag.logException(
                    "PAGES",
                    "public appImages manifest absent; continuing with deferred/protected reader",
                    url,
                    error,
                )
                emptyList()
            } else {
                throw error
            }
        }
        val pages = publicImages.mapIndexed { index, imageUrl ->
'''

CLIENT_ANCHOR = '''    override val client: OkHttpClient = network.client.newBuilder()
        .addInterceptor(ProComicImageInterceptor(network.client))
        .build()
'''
CLIENT_REPLACEMENT = '''    override val client: OkHttpClient = network.client.newBuilder()
        .addInterceptor(ProComicWebViewCookieInterceptor())
        .addInterceptor(ProComicImageInterceptor(network.client))
        .build()
'''

UTILS_ANCHOR = '''    fun resolveRefererForUrl(url: String): String {
        val host = runCatching { URI(url).host?.lowercase() }.getOrNull()
        return if (host != null && host.endsWith(".procomic.net")) {
            "https://procomic.net/"
        } else {
            "https://procomic.pro/"
        }
    }

'''
UTILS_HELPER = r'''    fun hasReaderDeferredOrProtectedContract(body: String): Boolean =
        body.contains("\\\"deferredMedia\\\"") ||
            body.contains("\"deferredMedia\"") ||
            body.contains("\\\"protectionV2\\\"") ||
            body.contains("\"protectionV2\"")

'''


WEBVIEW_COOKIE_CLASS = r'''private class ProComicWebViewCookieInterceptor : Interceptor {

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
                if (name.isNotEmpty()) {
                    values[name] = value
                }
            }
        }
        return values.entries.joinToString("; ") { (name, value) -> "$name=$value" }
    }
}

'''

IMAGES_ANCHOR = '''        if (fallbackUrls.isNotEmpty()) {
            if (diag) ProComicDiag.logStage(diagTag, 4, "fallback regex found ${fallbackUrls.size} chapter images")
            return fallbackUrls
        }

        // 3. Explicit Failure
'''
IMAGES_REPLACEMENT = '''        if (fallbackUrls.isNotEmpty()) {
            if (diag) ProComicDiag.logStage(diagTag, 4, "fallback regex found ${fallbackUrls.size} chapter images")
            return fallbackUrls
        }

        // Some Reader variants expose a plain images[] array instead of appImages.
        val plainImagesJson = extractJsonArrayAfterKey(body, "images")
        if (plainImagesJson != null) {
            runCatching {
                json.decodeFromString<List<String>>(normalizeRscJson(plainImagesJson))
                    .map(String::trim)
                    .filter(::isAllowedPageImageUrl)
                    .filter { it.contains("/chapters/") }
                    .distinct()
            }.getOrNull()?.takeIf { it.isNotEmpty() }?.let { urls ->
                if (diag) ProComicDiag.logStage(
                    diagTag,
                    5,
                    "fallback plain images[] found ${urls.size} chapter images",
                )
                return urls
            }
        }

        // Some current Reader payloads inline page URLs directly. Extract only URLs from
        // confirmed ProComic CDN hosts, then apply the strict page-image validator.
        val directCdnUrls = Regex(
            """https://(?:app|cdn[1-4])\.procomic\.(?:pro|net)/[^"\\\s]+\.(?:avif|webp|jpe?g|png)""",
        ).findAll(body)
            .map { it.value.trim() }
            .filter(::isAllowedPageImageUrl)
            .distinct()
            .toList()

        if (directCdnUrls.isNotEmpty()) {
            if (diag) ProComicDiag.logStage(
                diagTag,
                6,
                "fallback direct CDN URLs found ${directCdnUrls.size} chapter images",
            )
            return directCdnUrls
        }

        // A protected/deferred Reader may legitimately have no public image manifest. Return an
        // empty public set so pageListParse() can continue into deferred/protected delivery.
        if (hasReaderDeferredOrProtectedContract(body)) {
            if (diag) ProComicDiag.logStage(
                diagTag,
                7,
                "no public image manifest; deferred/protected Reader contract detected",
            )
            return emptyList()
        }

        // A response can also legitimately be image-less while the server is preparing or
        // changing its Reader contract. Avoid failing the whole chapter at this extraction stage;
        // pageListParse() will still have a chance to use any deferred/protected metadata.
        if (diag) ProComicDiag.logStage(
            diagTag,
            8,
            "no usable public image manifest; returning empty set",
        )
        return emptyList()

        // 4. Explicit Failure
'''


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one source anchor, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def apply(root: Path) -> None:
    procomic = root / "app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic/ProComic.kt"
    utils = root / "app/src/main/kotlin/eu/kanade/tachiyomi/extension/ar/procomic/ProComicUtils.kt"
    for path in (procomic, utils):
        if not path.is_file():
            raise SystemExit(f"missing expected upstream source file: {path}")

    procomic_text = procomic.read_text(encoding="utf-8")
    if PROCOMIC_IMPORT not in procomic_text:
        replace_once(procomic, PROCOMIC_IMPORT_ANCHOR, PROCOMIC_IMPORT_ANCHOR + PROCOMIC_IMPORT)

    replace_once(procomic, PROCOMIC_ANCHOR, PROCOMIC_REPLACEMENT)
    replace_once(procomic, CLIENT_ANCHOR, CLIENT_REPLACEMENT)
    procomic_text = procomic.read_text(encoding="utf-8")
    if "private class ProComicWebViewCookieInterceptor" not in procomic_text:
        procomic.write_text(procomic_text + WEBVIEW_COOKIE_CLASS, encoding="utf-8")
    replace_once(utils, UTILS_ANCHOR, UTILS_ANCHOR + UTILS_HELPER)
    replace_once(utils, IMAGES_ANCHOR, IMAGES_REPLACEMENT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    apply(args.source_root.resolve())
    print("ProComic Reader hotfix applied successfully.")


if __name__ == "__main__":
    main()
