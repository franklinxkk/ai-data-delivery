#!/usr/bin/env python3
"""Build a deterministic skill archive from tracked runtime files only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = {"SKILL.md", "README.md", "LICENSE", "requirements.txt"}
DIRECTORIES = {"scripts", "references", "mocks", "examples"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-dirty", action="store_true", help="development preview only")
    args = ap.parse_args()
    if not args.allow_dirty and git("status", "--porcelain").strip():
        ap.error("source is dirty; commit first or explicitly build a development preview")
    metadata = yaml.safe_load((ROOT / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1])
    version = str(metadata["metadata"]["version"])
    tracked = git("ls-files", "-z").decode("utf-8").split("\0")
    paths = sorted(p for p in tracked if p and (p in FILES or p.split("/")[0] in DIRECTORIES))
    if not FILES <= set(paths):
        ap.error("missing tracked runtime entry files")
    if any(p.endswith((".db", ".pyc")) or "__pycache__" in p or p.endswith(("actual.jsonl", "report.json")) for p in paths):
        ap.error("generated database/report/cache found in tracked runtime assets")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"ai-data-delivery_v{version}.skill"
    manifest = {"name": metadata["name"], "version": version,
                "source_commit": git("rev-parse", "HEAD").decode().strip(),
                "development_preview": args.allow_dirty,
                "files": []}
    entries = {}
    for name in paths:
        data = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        entries[name] = data
        manifest["files"].append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    entries["BUILD.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo("ai-data-delivery/" + name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            package.writestr(info, data)
    with zipfile.ZipFile(archive) as package:
        if package.testzip():
            raise RuntimeError("archive CRC check failed")
        for name, data in entries.items():
            if package.read("ai-data-delivery/" + name) != data:
                raise RuntimeError("archive content differs from source")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / "SHA256SUMS.txt").write_text(f"{sha}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "sha256": sha, "runtime_files": len(paths), "source_commit": manifest["source_commit"], "development_preview": args.allow_dirty}, ensure_ascii=False))


if __name__ == "__main__":
    main()
