# ProComic Mihon Repository

Isolated distribution repository for the Arabic ProComic Mihon extension.

## Published release

**ProComic 1.5.6 — versionCode 12**

The APK currently published under `main` is the legacy 1.5.6 custom build.

The authenticated Reader implementation in this repository has since been redesigned on a separate development branch and must not be described as runtime-verified until an Android test confirms the real ProComic account/session flow.

## Development Reader architecture

The development implementation:

- keeps the exact ProComic `.pro` / `.net` origin instead of forcing a domain rewrite;
- uses an Android WebView in Mihon's main process/default WebView profile;
- preserves the normal CookieManager and Web Storage state without fabricating cookies or tokens;
- distinguishes Safe Browsing, login-required, and premium/server-entitlement states;
- keeps the upstream Reader parser and protected tile validation;
- can fall back to browser context for denied deferred-media, protected-map, image, and tile requests;
- does not bypass payment, entitlement, Safe Browsing, login, or other server-side authorization.

The account itself must legitimately have permission to read the requested chapter.

## Login-required chapters

Some ProComic chapters are restricted by the site to authenticated accounts. Mihon cannot reuse a login session from an external browser because web sessions are stored in the Android WebView profile and cookies are scoped to their domain. The extension therefore provides a source setting named **تسجيل الدخول إلى ProComic** that opens the current `procomic.pro` origin inside Mihon's WebView. Log in there once, then retry the chapter.

This does not unlock premium chapters and does not bypass server authorization. If ProComic still reports that the account is not authorized, the chapter remains inaccessible until the account has legitimate access.

## Add to Mihon

Use:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/repo.json

## Source and upstream

Source: https://procomic.pro/

Upstream implementation: https://github.com/LoneVertex/mihon-extension-ar-procomic

The pinned release baseline for the current development pipeline is upstream `v1.5.1`.

## Signing

The legacy 1.5.6 APK was produced with a temporary signing identity.

The release pipeline now requires a persistent keystore and a separately pinned certificate fingerprint before publishing a new distributable version. This is required to prevent accidental signing-identity changes between releases.