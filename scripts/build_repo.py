#!/usr/bin/env python3
import argparse, gzip, hashlib, json
from pathlib import Path

import os, shutil, subprocess, tempfile

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



PATCHED_VERSION_CODE = 8
PATCHED_VERSION_NAME = "1.5.2"
PATCHED_APK_NAME = "procomic-release-v1.5.2.apk"
UPSTREAM_REPO = "https://github.com/LoneVertex/mihon-extension-ar-procomic.git"


def _write_github_env(values):
    env_file = os.environ.get("GITHUB_ENV")
    if not env_file:
        return
    with open(env_file, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _read_current_publication():
    path = ROOT / "publication.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _latest_build_tools():
    android_home = os.environ.get("ANDROID_HOME")
    if not android_home:
        raise SystemExit("ANDROID_HOME is required to build the patched APK")
    build_tools = sorted((Path(android_home) / "build-tools").glob("*"))
    if not build_tools:
        raise SystemExit("Android build-tools are not installed")
    return build_tools[-1]


def _set_version(source_root):
    gradle_file = source_root / "app" / "build.gradle.kts"
    text = gradle_file.read_text(encoding="utf-8")
    if "versionCode = 7" not in text or 'versionName = "1.5.1"' not in text:
        raise SystemExit("unexpected upstream version baseline; refusing automatic patch build")
    text = text.replace("versionCode = 7", "versionCode = 8", 1)
    text = text.replace('versionName = "1.5.1"', 'versionName = "1.5.2"', 1)
    gradle_file.write_text(text, encoding="utf-8")


def _build_patched_apk():
    work_parent = Path(tempfile.mkdtemp(prefix="wyros-procomic-"))
    source_root = work_parent / "upstream"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", UPSTREAM_REPO, str(source_root)],
            check=True,
        )
        subprocess.run(
            ["python3", str(ROOT / "scripts" / "apply_reader_hotfix.py"), str(source_root)],
            check=True,
        )
        _set_version(source_root)
        subprocess.run(
            [str(source_root / "gradlew"), ":app:assembleRelease", "--no-daemon", "--stacktrace"],
            cwd=source_root,
            check=True,
        )
        unsigned = source_root / "app" / "build" / "outputs" / "apk" / "release" / "app-release-unsigned.apk"
        if not unsigned.is_file() or unsigned.stat().st_size < 100_000:
            raise SystemExit("patched release APK was not produced")

        build_tools = _latest_build_tools()
        keytool = shutil.which("keytool")
        if not keytool:
            raise SystemExit("keytool not found")
        keystore = work_parent / "release.jks"
        password = hashlib.sha256(os.urandom(32)).hexdigest()
        subprocess.run(
            [
                keytool, "-genkeypair",
                "-keystore", str(keystore),
                "-storepass", password,
                "-keypass", password,
                "-alias", "procomic",
                "-keyalg", "RSA",
                "-keysize", "4096",
                "-validity", "3650",
                "-dname", "CN=WYROS ProComic, OU=WYROS, O=ProComic",
            ],
            check=True,
        )
        signed = ROOT / "apk" / PATCHED_APK_NAME
        signed.parent.mkdir(parents=True, exist_ok=True)
        apksigner = build_tools / "apksigner"
        subprocess.run(
            [
                str(apksigner), "sign",
                "--ks", str(keystore),
                "--ks-pass", f"pass:{password}",
                "--ks-key-alias", "procomic",
                "--key-pass", f"pass:{password}",
                "--out", str(signed),
                str(unsigned),
            ],
            check=True,
        )
        subprocess.run(
            [str(apksigner), "verify", "--verbose", "--print-certs", str(signed)],
            check=True,
        )
        lines = subprocess.check_output(
            [str(apksigner), "verify", "--print-certs", str(signed)],
            text=True,
        ).splitlines()
        cert = next(
            (line.split("SHA-256 digest:", 1)[1].strip().replace(":", "")
             for line in lines if "SHA-256 digest:" in line),
            "",
        )
        if len(cert) != 64:
            raise SystemExit("failed to extract patched APK signing fingerprint")
        sha256 = hashlib.sha256(signed.read_bytes()).hexdigest()
        return cert, sha256
    finally:
        shutil.rmtree(work_parent, ignore_errors=True)


def maybe_prepare_patched_release(upstream_version_code, upstream_version_name):
    current = _read_current_publication()
    existing = ROOT / "apk" / PATCHED_APK_NAME

    # Once the patched release is published, keep it in place while the upstream channel
    # remains older. This prevents the scheduled sync job from silently downgrading the repo.
    if (
        upstream_version_code < PATCHED_VERSION_CODE
        and current
        and int(current.get("versionCode", 0)) >= PATCHED_VERSION_CODE
        and existing.is_file()
    ):
        for stale in (ROOT / "apk").glob("*.apk"):
            if stale.name != PATCHED_APK_NAME:
                stale.unlink()
        fingerprint = str(current.get("signingKeyFingerprint", "")).strip()
        if len(fingerprint) != 64:
            raise SystemExit("published patched fingerprint is invalid")
        _write_github_env({
            "UPSTREAM_ASSET_NAME": PATCHED_APK_NAME,
            "UPSTREAM_VERSION_CODE": PATCHED_VERSION_CODE,
            "UPSTREAM_VERSION_NAME": PATCHED_VERSION_NAME,
            "UPSTREAM_FINGERPRINT": fingerprint,
            "UPSTREAM_SHA256": hashlib.sha256(existing.read_bytes()).hexdigest(),
        })
        return PATCHED_VERSION_CODE, PATCHED_VERSION_NAME, PATCHED_APK_NAME, fingerprint

    if upstream_version_code >= PATCHED_VERSION_CODE:
        return upstream_version_code, upstream_version_name, None, None

    print("Upstream is older than the WYROS Reader hotfix release; building ProComic 1.5.2.")
    for stale in (ROOT / "apk").glob("*.apk"):
        stale.unlink()
    fingerprint, sha256 = _build_patched_apk()
    _write_github_env({
        "UPSTREAM_ASSET_NAME": PATCHED_APK_NAME,
        "UPSTREAM_VERSION_CODE": PATCHED_VERSION_CODE,
        "UPSTREAM_VERSION_NAME": PATCHED_VERSION_NAME,
        "UPSTREAM_FINGERPRINT": fingerprint,
        "UPSTREAM_SHA256": sha256,
    })
    return PATCHED_VERSION_CODE, PATCHED_VERSION_NAME, PATCHED_APK_NAME, fingerprint

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
    extension_list = message(1, extension)
    contact = text(1, REPO_WEBSITE) + text(2, REPO_WEBSITE)
    index = text(1, REPO_NAME) + text(2, "WYROS") + text(3, fingerprint) + message(4, contact) + message(101, extension_list)
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

    code, name, patched_name, patched_fingerprint = maybe_prepare_patched_release(
        a.version_code,
        a.version_name,
    )
    if patched_name is not None:
        a.version_code = code
        a.version_name = name
        a.apk_name = patched_name
        a.fingerprint = patched_fingerprint

    apk = ROOT / "apk" / a.apk_name
    if not apk.is_file() or apk.stat().st_size < 100000:
        raise SystemExit("APK missing or unexpectedly small")
    write_indexes(a.version_code, a.version_name, a.apk_name, a.fingerprint)
