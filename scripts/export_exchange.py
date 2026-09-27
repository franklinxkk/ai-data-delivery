#!/usr/bin/env python3
"""export_exchange.py — 运营段：语义资产交换导出（ai-data-delivery v0.0.3）

RULE-CONSUME-01 的交付面：发给甲方/其他系统时，模型、字典、gold 集要作为"一个版本化
整体"导出，带 sha256 清单——对方可验完整性，后续可对账版本漂移。

用法：
  python export_exchange.py --model semantic.yaml --out exchange/ \
      [--cases cases.json] [--dictionary dictionary.md]
产物：
  exchange/semantic.yaml        模型原样拷贝
  exchange/dictionary.md        口径字典（不给 --dictionary 则现场生成）
  exchange/cases.json           gold 用例（可选）
  exchange/manifest.json        版本/时间戳/每文件 sha256
退出码：0 成功；2 用法错误。
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="语义资产交换导出")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True, help="导出目录")
    ap.add_argument("--cases", default=None)
    ap.add_argument("--dictionary", default=None, help="不给则现场生成")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    m = yaml.safe_load(open(args.model, encoding="utf-8"))
    files = []

    dst = os.path.join(args.out, "semantic.yaml")
    shutil.copyfile(args.model, dst)
    files.append(dst)

    dic = args.dictionary
    if not dic:
        dic = os.path.join(args.out, "dictionary.md")
        subprocess.run([sys.executable, os.path.join(HERE, "gen_dictionary.py"),
                        "--model", args.model, "--out", dic], check=True)
    else:
        shutil.copyfile(dic, os.path.join(args.out, "dictionary.md"))
        dic = os.path.join(args.out, "dictionary.md")
    files.append(dic)

    if args.cases:
        dst = os.path.join(args.out, "cases.json")
        shutil.copyfile(args.cases, dst)
        files.append(dst)

    manifest = {
        "name": m.get("name", "?"),
        "version": m.get("version", "?"),
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": [{"path": os.path.basename(f), "bytes": os.path.getsize(f),
                   "sha256": sha256(f)} for f in files],
    }
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"导出完成 → {args.out}（版本 {manifest['version']}，{len(files)} 个文件）")
    for it in manifest["files"]:
        print(f"  {it['path']:20s} {it['bytes']:>8d} B  {it['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
