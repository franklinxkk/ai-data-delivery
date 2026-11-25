#!/usr/bin/env python3
"""Check a local release tree, installation ZIP and optional release notes.

Supply one literal per line in a separate private UTF-8 file. Only aggregate
counts are printed. Names and decoded text are compared after Unicode NFKC
normalization and case folding, including literal Unicode escapes. Readable
formats are UTF-8 and BOM-marked UTF-16/32. Opaque bodies are counted for
separate review (including images, nested archives and unsupported encodings).
This does not inspect Git history, OCR, archive metadata or embedded binaries.
Exit 0 = no match in scanned names/text, 1 = match, 2 = incomplete/error.
"""

import argparse
import codecs
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
import zipfile


MAX_BODY = 64 * 1024 * 1024
ESCAPES = re.compile(
    r"\\u([dD][89aAbB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
    r"|\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})|\\u\{([0-9a-fA-F]{1,6})\}"
)


class Incomplete(Exception):
    """Message must be safe for public logs."""


def unescape(match):
    high, low, short, long, braced = match.groups()
    if high:
        return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + int(low, 16) - 0xDC00)
    point = int(short or long or braced, 16)
    return chr(point) if point <= 0x10FFFF else match.group()


def normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


def matches(value, terms):
    literal = normalized(value)
    if any(term in literal for term in terms):
        return True
    if "\\u" in value or "\\U" in value:
        decoded = normalized(ESCAPES.sub(unescape, value))
        return any(term in decoded for term in terms)
    return False


def decode_text(data):
    encoding = "utf-8-sig"
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    try:
        value = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    return None if "\x00" in value else value


@dataclass
class Counts:
    names: int = 0
    matched_names: int = 0
    text_bodies: int = 0
    matched_bodies: int = 0
    opaque_bodies: int = 0

    def name(self, name, terms):
        self.names += 1
        self.matched_names += matches(name, terms)

    def body(self, data, terms):
        value = decode_text(data)
        if value is None:
            self.opaque_bodies += 1
        else:
            self.text_bodies += 1
            self.matched_bodies += matches(value, terms)


def check_size(size):
    if size > MAX_BODY:
        raise Incomplete("input exceeds the 64 MiB per-body inspection limit")


def private_terms(path):
    check_size(path.stat().st_size)
    terms = {normalized(line.strip()) for line in path.read_text(encoding="utf-8-sig").splitlines()
             if line.strip()}
    if not terms:
        raise Incomplete("empty exclusion list")
    return terms


@contextmanager
def git_blobs(git, env):
    with subprocess.Popen([*git, "cat-file", "--batch"], env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            yield process
        finally:
            process.stdin.close()
            process.stdout.close()
        if process.wait() != 0:
            raise Incomplete("Git object read failed")


def scan_tree(repo, ref, terms):
    git = ["git", "-C", str(repo)]
    env = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
           "GIT_TERMINAL_PROMPT": "0"}

    def read_git(*args):
        return subprocess.check_output([*git, *args], stderr=subprocess.DEVNULL, env=env)

    tree = read_git("rev-parse", "--verify", "--end-of-options", ref + "^{tree}").strip().decode("ascii")
    entries = read_git("ls-tree", "-r", "-t", "-z", "--full-tree", tree).split(b"\0")
    counts = Counts()
    with git_blobs(git, env) as blobs:
        for entry in filter(None, entries):
            header, path = entry.split(b"\t", 1)
            _, kind, oid = header.split()
            counts.name(path.decode("utf-8"), terms)
            if kind == b"tree":
                continue
            if kind != b"blob":
                raise Incomplete("Git tree contains an uninspected external object")
            blobs.stdin.write(oid + b"\n")
            blobs.stdin.flush()
            info = blobs.stdout.readline().split()
            if len(info) != 3 or info[:2] != [oid, b"blob"]:
                raise Incomplete("Git object unavailable")
            size = int(info[2])
            check_size(size)
            data = blobs.stdout.read(size)
            if len(data) != size or blobs.stdout.read(1) != b"\n":
                raise Incomplete("incomplete Git object")
            counts.body(data, terms)
    return counts


def scan_zip(path, terms):
    counts = Counts()
    counts.name(path.name, terms)
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            counts.name(entry.orig_filename, terms)
            if not entry.is_dir() or entry.file_size:
                check_size(entry.file_size)
                counts.body(archive.read(entry), terms)
    return counts


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse otherwise echoes unrecognized arguments, including private paths.
        self.exit(2, "Invalid arguments. Use --help for usage.\n")


def main(argv=None):
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ref", default="HEAD", help="commit, tag or tree to inspect (default HEAD)")
    parser.add_argument("--terms-file", required=True, type=Path, help="private local UTF-8 list")
    parser.add_argument("--zip", required=True, type=Path, help="installation ZIP")
    parser.add_argument("--release-notes", type=Path, help="optional release notes in a supported text encoding")
    args = parser.parse_args(argv)
    stage = "terms"
    try:
        terms = private_terms(args.terms_file)
        stage = "tree"
        results = {"tree": scan_tree(args.repo, args.ref, terms)}
        stage = "zip"
        results["zip"] = scan_zip(args.zip, terms)
        if args.release_notes is not None:
            stage = "notes"
            notes = Counts()
            notes.name(args.release_notes.name, terms)
            check_size(args.release_notes.stat().st_size)
            notes.body(args.release_notes.read_bytes(), terms)
            if notes.opaque_bodies:
                raise Incomplete("release notes have unsupported text encoding")
            results["notes"] = notes
    except Exception as exc:
        # OS, Git and ZIP exceptions can include private paths, terms or bytes.
        reason = str(exc) if isinstance(exc, Incomplete) else "could not inspect input"
        print(json.dumps({"result": "incomplete", "stage": stage, "reason": reason}))
        return 2
    hit = any(counts.matched_names or counts.matched_bodies for counts in results.values())
    print(json.dumps({"result": "match" if hit else "no_match_in_scanned_scope",
                      "counts": {key: asdict(value) for key, value in results.items()}}))
    return int(hit)


if __name__ == "__main__":
    sys.exit(main())
