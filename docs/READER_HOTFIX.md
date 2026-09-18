# Reader hotfix — 2026-09-18

The Android screenshot exposed this Reader failure on the current ProComic release:

"ProComic Reader: No 'appImages' manifest found in response"

The hotfix in patches/reader-no-appimages-v2.patch addresses two Reader response variants:

1. A chapter response can expose a plain images[] list instead of appImages.
2. A response can contain the deferred/protected Reader contract without a public appImages manifest. The parser must continue into deferredMedia/protectionV2 instead of aborting.

The patch is deliberately limited to Reader parsing. It does not disable paid/access checks and does not fabricate page URLs.

## Release boundary

WYROS-System/ProComic-Mihon currently mirrors the upstream signed v1.5.1 APK. A source patch changes the APK bytes and therefore needs a new APK signed with the extension signing key before it can replace the trusted release. The upstream private signing key is not stored in this repository, so the existing signed v1.5.1 APK has not been replaced automatically.
