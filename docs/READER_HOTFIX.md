# ProComic Reader fix

The Reader had two independent failure modes:

1. Some responses do not expose a public `appImages` manifest.
2. Authenticated WebView sessions were not being applied to all Reader HTTP requests.

The current build pipeline applies both fixes.

## Authentication path

After logging in through Mihon's WebView, the extension reads the WebView's ProComic cookies through Android's `CookieManager`. The authenticated cookie header is merged with the existing OkHttp cookie header for requests to the actual ProComic destination URL.

The same session bridge is applied to:

- chapter/Reader page-list requests
- deferred-media requests
- protected-map requests
- protected CDN tile requests

Reader requests also use `Cache-Control: no-cache` so a previously cached guest response is not reused after login.

This does not bypass payment, entitlement, or server-side security controls. The account itself must have access to the chapter.

## Release

The maintained WYROS release is ProComic 1.5.5 (versionCode 11).