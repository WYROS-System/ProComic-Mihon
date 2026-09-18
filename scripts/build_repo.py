#!/usr/bin/env python3
import argparse, gzip, hashlib, json
from pathlib import Path

PACKAGE = "eu.kanade.tachiyomi.extension.ar.procomic"
SOURCE_NAME = "ProComic"
SOURCE_LANG = "ar"
SOURCE_BASE = "https://procomic.pro"
SOURCE_ID = 6818345659309721544
CONTENT_WARNING = "CONTENT_WARNING_SAFE"
EXTENSION_LIB = "1.6"
REPO_NAME = "WYROS ProComic"
REPO_WEBSITE = "https://github.com/WYROS-System/ProComic-Mihon"
REPO_RAW = "https://raw.githubusercontent.com/WYROS-System/ProComic-Mihon/main"
ROOT = Path(__file__).resolve().parents[1]

def varint(value):
    if value < 0:
        raise ValueError("protobuf varints here must be non-negative")
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        out.append(b | 0x80 if value else b)
        if not value:
            return bytes(out)

def tag(number, wire):
    return varint((number << 3) | wire)

def scalar(number, value):
    return b"" if value == 0 else tag(number, 0) + varint(value)

def text(number, value):
    if not value:
        return b""
    data = value.encode("utf-8")
    return tag(number, 2) + varint(len(data)) + data

def message(number, body):
    return tag(number, 2) + varint(len(body)) + body

def source_message():
    return scalar(1, SOURCE_ID) + text(2, SOURCE_NAME) + text(3, SOURCE_LANG) + text(4, SOURCE_BASE)

def extension_message(version_code, version_name, apk_name, fingerprint):
    resources = (
        text(1, f"{REPO_RAW}/apk/{apk_name}")
        + text(2, f"{REPO_RAW}/icon/{PACKAGE}.png")
    )
    return (
        text(1, SOURCE_NAME)
        + text(2, PACKAGE)
        + message(3, resources)
        + text(4, EXTENSION_LIB)
        + scalar(5, version_code)
        + text(6, version_name)
        + scalar(7, 1)
        + message(8, source_message())
    )

def write_indexes(version_code, version_name, apk_name, fingerprint):
    public_apk = f"{REPO_RAW}/apk/{apk_name}"
    public_icon = f"{REPO_RAW}/icon/{PACKAGE}.png"
    legacy = [{
        "name": SOURCE_NAME,
        "pkg": PACKAGE,
        "apk": public_apk,
        "lang": SOURCE_LANG,
        "code": version_code,
        "version": version_name,
        "nsfw": 0,
    }]
    (ROOT / "index.min.json").write_text(json.dumps(legacy, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    modern = {
        "name": REPO_NAME,
        "badgeLabel": "WYROS",
        "signingKey": fingerprint,
        "contact": {"website": REPO_WEBSITE},
        "extensionList": {"extensions": [{
            "name": SOURCE_NAME,
            "packageName": PACKAGE,
            "resources": {"apkUrl": public_apk, "iconUrl": public_icon},
            "extensionLib": EXTENSION_LIB,
            "versionCode": str(version_code),
            "versionName": version_name,
            "contentWarning": CONTENT_WARNING,
            "sources": [{
                "id": str(SOURCE_ID),
                "name": SOURCE_NAME,
                "language": SOURCE_LANG,
                "homeUrl": SOURCE_BASE,
                "mirrorUrls": [],
            }],
        }]}
    }
    (ROOT / "index.json").write_text(json.dumps(modern, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repo = {
        "index_v2": f"{REPO_RAW}/index.pb",
        "meta": {"name": REPO_NAME, "website": REPO_WEBSITE, "signingKeyFingerprint": fingerprint},
    }
    (ROOT / "repo.json").write_text(json.dumps(repo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extension = extension_message(version_code, version_name, apk_name, fingerprint)
    contact = text(1, REPO_WEBSITE) + text(2, REPO_WEBSITE)
    index = text(1, REPO_NAME) + text(2, "WYROS") + text(3, fingerprint) + message(4, contact) + message(101, extension)
    (ROOT / "index.pb").write_bytes(gzip.compress(index, mtime=0))
    record = {
        "package": PACKAGE, "name": SOURCE_NAME, "language": SOURCE_LANG,
        "versionCode": version_code, "versionName": version_name, "apk": apk_name,
        "sha256": hashlib.sha256((ROOT / "apk" / apk_name).read_bytes()).hexdigest(),
        "signingKeyFingerprint": fingerprint, "sourceUrl": SOURCE_BASE,
    }
    (ROOT / "publication.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version-code", type=int, required=True)
    ap.add_argument("--version-name", required=True)
    ap.add_argument("--apk-name", required=True)
    ap.add_argument("--fingerprint", required=True)
    a = ap.parse_args()
    if a.version_code <= 0 or not a.version_name or len(a.fingerprint) != 64:
        raise SystemExit("invalid publication metadata")
    apk = ROOT / "apk" / a.apk_name
    if not apk.is_file() or apk.stat().st_size < 100000:
        raise SystemExit("APK missing or unexpectedly small")
    write_indexes(a.version_code, a.version_name, a.apk_name, a.fingerprint)
