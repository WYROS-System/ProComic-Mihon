# ProComic Mihon Repository

Clean, isolated distribution repository for the Arabic ProComic Mihon extension.

## Current release

**ProComic 1.5.6 — versionCode 12**

This release includes an authenticated Reader fallback that uses a real Android WebView session. When the normal Reader request is denied or returns the site's Safe Browsing/login gate, the extension loads the same chapter in a WebView with JavaScript, DOM storage, cookies, and the site's normal browser session, then extracts the chapter media contract.

Image requests that receive HTTP 401/403 also have a browser-session fallback.

The implementation does not bypass payment, entitlement, login, or server-side authorization. The ProComic account must legitimately have access to the chapter, and any Safe Browsing preference required by ProComic must be changed through the site's own account/settings flow.

## Add to Mihon

Use:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/repo.json

## Source and upstream

Source: https://procomic.net/

Upstream implementation: https://github.com/LoneVertex/mihon-extension-ar-procomic

## Signing

The published WYROS APK is signed with the certificate fingerprint stored in repo.json.

The current release was intentionally published as a self-contained custom build. The signing key is not stored in this public repository. Future custom releases need to reuse a persistent private signing key to preserve seamless Android updates.
