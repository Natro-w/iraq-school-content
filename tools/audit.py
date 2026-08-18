"""Repository health + integrity audit tool.

Offline checks only (no network). Complements validate.py (content contract),
build.py (catalog determinism) and check_links.py (external URL liveness).

Run:
  python tools/audit.py health        repo hygiene snapshot (sizes, strays, secrets, CI)
  python tools/audit.py duplicates    exact-duplicate file groups (SHA-256)
  python tools/audit.py orphans       thumbnail <-> manifest mapping gaps
  python tools/audit.py urls          structural URL audit (hosts, scheme, relative)
  python tools/audit.py documents     non-JSON/non-JPG tracked files
  python tools/audit.py clean-check   git clean + validate + build --check + diff check

Exit codes: 0 = clean, 1 = issues found.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import REPO_ROOT, load_json, read_manifests  # noqa: E402

GIT_DIR = REPO_ROOT / ".git"
THUMBS_DIR = REPO_ROOT / "thumbnails"
CATALOG_DIR = REPO_ROOT / "catalog"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

STRAY_PATTERNS = [
    re.compile(r"\.(tmp|bak|old|orig|swp)$", re.I),
    re.compile(r"^(Thumbs\.db|\.DS_Store|desktop\.ini)$", re.I),
    re.compile(r"^~\$", re.I),
    re.compile(r"^\._", re.I),
]

SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(sk|pk)_(live|test)_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
]


def git(*args: str) -> list[str]:
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.stdout.splitlines()


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def tracked_files() -> list[str]:
    return git("ls-files")


def is_tracked(rel: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", "--", rel],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def scan_tree(root: Path, predicate) -> list[Path]:
    out = []
    for p in root.rglob("*"):
        if p.is_file() and predicate(p):
            out.append(p)
    return out


def cmd_health() -> int:
    issues: list[str] = []
    info: list[str] = []

    # repo size
    tree_size = dir_size(REPO_ROOT) - dir_size(GIT_DIR)
    git_size = dir_size(GIT_DIR)
    info.append(f"working tree: {tree_size:,} B, .git: {git_size:,} B, total {tree_size + git_size:,} B")
    if tree_size > 1_000_000_000:
        issues.append(f"working tree {tree_size:,} B exceeds 1 GB recommendation")
    if tree_size > 5_000_000_000:
        issues.append(f"working tree {tree_size:,} B exceeds 5 GB strong recommendation")

    # files
    n = len(tracked_files())
    info.append(f"tracked files: {n}")
    if n > 100_000:
        issues.append(">100k tracked files")

    # largest blobs in history
    objects = git("rev-list", "--objects", "--all")
    oid_to_path = {}
    for line in objects:
        parts = line.split()
        if len(parts) == 2:
            oid_to_path[parts[0]] = parts[1]
    if oid_to_path:
        batch = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "--batch-check=%(objectname) %(objectsize)"],
            input="\n".join(oid_to_path).encode(), capture_output=True,
        )
        sizes: dict[str, int] = {}
        for line in batch.stdout.decode(errors="replace").splitlines():
            oid, sz = line.split()
            if oid in oid_to_path:
                sizes[oid_to_path[oid]] = int(sz)
        top = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for path, sz in top:
            info.append(f"largest blob: {sz:,} B {path}")
            if sz > 50 * 1024 * 1024:
                issues.append(f"blob {path} ({sz:,} B) exceeds 50 MiB warning threshold")

    # stray files (tracked)
    for rel in tracked_files():
        name = Path(rel).name
        if any(p.search(name) for p in STRAY_PATTERNS):
            issues.append(f"stray/backup tracked file: {rel}")

    # untracked + ignored summary
    untracked = git("ls-files", "--others", "--exclude-standard")
    if untracked:
        issues.append(f"untracked files present ({len(untracked)}): {', '.join(untracked[:5])}")
    else:
        info.append("working tree clean (no untracked files)")

    # secrets in tracked tree
    hits: list[str] = []
    for rel in tracked_files():
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:2048]:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(data.decode("utf-8", errors="ignore")):
                hits.append(f"{rel}: {pat.pattern}")
    if hits:
        issues.append("potential secrets in tracked tree:")
        issues.extend(f"  {h}" for h in hits)
    else:
        info.append("no secret patterns in tracked tree")

    # branches / tags
    info.append(f"local branches: {', '.join(git('branch', '--format=%(refname:short)'))}")
    tags = git("tag")
    if tags:
        info.append(f"tags: {', '.join(tags)}")
    else:
        info.append("tags: none")

    # CI config
    wf = list(WORKFLOW_DIR.glob("*.yml")) + list(WORKFLOW_DIR.glob("*.yaml"))
    info.append(f"workflows: {', '.join(p.name for p in wf) or 'NONE'}")
    for p in wf:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(uses:\s*[^\s]+@[^\s]+)", txt):
            uses = m.group(1)
            ref = uses.rsplit("@", 1)[-1]
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                issues.append(f"{p.name}: mutable action ref {uses} (pin to full commit SHA)")
            else:
                info.append(f"{p.name}: pinned {uses}")
        if "permissions:" not in txt:
            issues.append(f"{p.name}: no explicit permissions block")
    if not (REPO_ROOT / ".github" / "dependabot.yml").is_file():
        issues.append(".github/dependabot.yml missing (github-actions weekly recommended)")
    if not (REPO_ROOT / ".gitattributes").is_file():
        issues.append(".gitattributes missing")

    # gitignore coverage
    gi = REPO_ROOT / ".gitignore"
    if not gi.is_file():
        issues.append(".gitignore missing")
    else:
        info.append(f".gitignore present ({gi.stat().st_size} B)")

    # LFS check
    attrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8", errors="replace") if (REPO_ROOT / ".gitattributes").is_file() else ""
    if "filter=lfs" in attrs:
        info.append("LFS filters configured")
    else:
        info.append("no LFS filters (repo under 1 GB, LFS not required)")

    print("\n".join(info))
    if issues:
        print("\nISSUES:")
        print("\n".join(f"- {i}" for i in issues))
        return 1
    print("\nhealth: OK")
    return 0


def cmd_duplicates() -> int:
    hashes: dict[str, list[str]] = defaultdict(list)
    for p in scan_tree(REPO_ROOT, lambda f: GIT_DIR not in f.parents):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        hashes[h].append(str(p.relative_to(REPO_ROOT)).replace("\\", "/"))
    groups = {h: files for h, files in hashes.items() if len(files) > 1}
    total_bytes = 0
    for h, files in sorted(groups.items(), key=lambda kv: -kv[1][0].count("/")):
        sz = (REPO_ROOT / files[0]).stat().st_size
        total_bytes += sz * (len(files) - 1)
        print(f"{len(files)}x {sz:,} B: {', '.join(files)}")
    print(f"duplicate groups: {len(groups)}, redundant bytes: {total_bytes:,}")
    return 0 if not groups else 1


def _thumb_refs() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    refs: dict[str, list[str]] = {}
    for kind in ("books", "notes"):
        for m in read_manifests(kind):
            u = m.get("pdf_url", "")
            if u:
                h = hashlib.md5(u.encode()).hexdigest() + ".jpg"
                refs.setdefault(h, []).append(f"{kind}:{m['id']}")
    return refs, {}


def cmd_orphans() -> int:
    refs, _ = _thumb_refs()
    present = {p.name for p in THUMBS_DIR.iterdir()} if THUMBS_DIR.is_dir() else set()
    orphans = sorted(present - set(refs))
    missing = sorted(set(refs) - present)
    for f in orphans:
        print(f"ORPHAN thumb (no manifest): {f}")
    if missing:
        print(f"missing thumbs (manifest w/o file, app falls back to network URL): {len(missing)}")
    print(f"thumbs: {len(present)}, orphan: {len(orphans)}, missing: {len(missing)}")
    return 0 if not orphans else 1


def cmd_urls() -> int:
    url_re = re.compile(r"^https://[a-zA-Z0-9.-]+\.[a-z]{2,}")
    from urllib.parse import urlparse

    hosts: defaultdict[str, int] = defaultdict(int)
    bad: list[str] = []
    count = 0
    for kind in ("books", "notes"):
        for m in read_manifests(kind):
            for fld in ("pdf_url", "cover_url", "metadata_url", "source_url"):
                u = m.get(fld)
                if not u:
                    continue
                count += 1
                if not url_re.match(u):
                    bad.append(f"{kind}:{m['id']}:{fld}: {u}")
                    continue
                hosts[urlparse(u).netloc] += 1
    for h, c in sorted(hosts.items()):
        print(f"host {h}: {c} urls")
    for b in bad:
        print(f"BAD {b}")
    print(f"urls: {count}, hosts: {len(hosts)}, bad: {len(bad)}")
    return 0 if not bad else 1


def cmd_documents() -> int:
    bins = []
    for rel in tracked_files():
        if rel.startswith("thumbnails/"):
            continue
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        if rel.endswith(".json") or rel.endswith(".py") or rel.endswith(".md") or rel.endswith(".yml") or rel.endswith(".yaml") or rel.endswith(".gitignore") or rel.endswith(".env"):
            continue
        bins.append(rel)
    for b in bins:
        print(f"non-manifest artifact tracked: {b}")
    print(f"documents: {len(bins)}")
    return 0 if not bins else 1


def cmd_clean_check() -> int:
    issues = []
    st = git("status", "--porcelain")
    if st:
        issues.append("git status not clean:")
        issues.extend(f"  {s}" for s in st)
    diff_check = git("diff", "--check")
    if diff_check:
        issues.append("git diff --check failed:")
        issues.extend(f"  {d}" for d in diff_check)
    r = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "validate.py"), "--strict"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    issues.append(f"validate --strict: exit {r.returncode}")
    if r.stdout:
        issues.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "build.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    issues.append(f"build --check: exit {r.returncode} :: {r.stdout.strip()}")
    if r.returncode:
        issues.append(r.stderr.strip() or "catalog drift")
    print("\n".join(issues))
    bad = st or diff_check or r.returncode != 0
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["health", "duplicates", "orphans", "urls", "documents", "clean-check"])
    args = ap.parse_args()
    return {
        "health": cmd_health,
        "duplicates": cmd_duplicates,
        "orphans": cmd_orphans,
        "urls": cmd_urls,
        "documents": cmd_documents,
        "clean-check": cmd_clean_check,
    }[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())