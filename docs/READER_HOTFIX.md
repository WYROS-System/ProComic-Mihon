# Reader hotfix — 2026-09-18

The Android screenshot exposed:

"ProComic Reader: No 'appImages' manifest found in response"

The source fix is in scripts/apply_reader_hotfix.py. It makes the Reader tolerant of two response variants:

- plain images[] instead of appImages
- deferredMedia/protectionV2 without a public appImages manifest

The patcher is anchor-checked: it refuses to modify an unexpected upstream source layout.

## Apply

From a checkout of the maintained upstream source:

    python3 /path/to/ProComic-Mihon/scripts/apply_reader_hotfix.py /path/to/mihon-extension-ar-procomic

Then run the upstream deterministic suites and the Android build.

## Release boundary

WYROS-System/ProComic-Mihon currently mirrors the upstream signed v1.5.1 APK. A patched APK has different bytes and therefore requires signing with the extension's release signing key before it can replace the trusted APK. That private signing key is not stored in this repository, so the currently published APK remains unchanged until a properly signed patched release is produced.

The hotfix itself is committed on branch hotfix/reader-missing-appimages-2026-09-18.
