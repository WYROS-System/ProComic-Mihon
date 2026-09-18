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

The workflow mirrors the signed APK instead of creating a new signing key in this repository. It runs on a 6-hour schedule and can also be started manually.

No login bypass, payment bypass, authentication bypass, or WebView automation is introduced by this repository.

## Verification limits

The upstream project reports passing deterministic software tests and clean APK builds, while direct physical Android-device validation is not something this repository can perform automatically. Mihon itself warns that third-party extensions have broad application access, so only install from repositories you trust.
