# ProComic Mihon Repository

Dedicated, isolated Mihon extension repository for the Arabic ProComic source.

## Source

Runtime content source:

https://procomic.pro/ar

The published APK is mirrored from the maintained ProComic Mihon implementation:
https://github.com/LoneVertex/mihon-extension-ar-procomic

The repository is intentionally separate from `WYROS-System/WYROS-System`.

## Add to Mihon

Preferred current repository descriptor:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/repo.json

Direct modern protobuf index:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/index.pb

Legacy JSON index is retained only for older clients:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/index.min.json

## Trust and updates

The synchronization workflow verifies the upstream GitHub release asset SHA-256, verifies the APK package/version, extracts the APK signing certificate SHA-256 fingerprint, and blocks automatic publication if an already-published signing key changes. This avoids silently changing the trust root.

The workflow builds the maintained WYROS Reader variant when upstream is older than the published patched version. The patched Reader bridges the authenticated ProComic WebView session into the extension HTTP requests, including protected-map and tile requests, while preserving normal cookie domain scoping. Login is performed on ProComic itself; the extension does not bypass payment, access controls, or server-side security checks.

## Verification limits

The upstream project reports passing deterministic software tests and clean APK builds, while direct physical Android-device validation is not something this repository can perform automatically. Mihon itself warns that third-party extensions have broad application access, so only install from repositories you trust.
