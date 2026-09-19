# ProComic Mihon Repository

A clean, isolated Mihon extension repository for the Arabic ProComic source.

## Current state

This repository is intentionally kept as a minimal distribution manifest while the Reader/authentication behavior is being audited.

The repository currently advertises the verified upstream ProComic release **v1.5.1**. No experimental Reader/authentication patch is distributed from this repository.

## Add to Mihon

Use:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/repo.json

Mihon will resolve the legacy index from:

https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main/index.min.json

## Source

https://procomic.net/

Upstream implementation:

https://github.com/LoneVertex/mihon-extension-ar-procomic

## Audit status

The previous WYROS Reader/authentication experiments were removed from the distribution tree because they were not validated end-to-end on a real Mihon device.

The next Reader implementation should first establish the site's actual authentication contract, including the login session, Safe Browsing state, domain/cookie scope, and the exact request that returns the full chapter image manifest.