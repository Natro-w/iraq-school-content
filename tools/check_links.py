"""External URL availability report for all content pdf_urls.

Run: python tools/check_links.py [--limit N] [--timeout S] [--skip]
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import read_manifests  # noqa: E402


def check(url: str, timeout: int) -> tuple[str, str, int | None]:
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": "iraq-school-content-linkcheck/1.0",
                "Range": "bytes=0-7",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            head = r.read(8)
            ok = head.startswith(b"%PDF")
            return url, ("PDF" if ok else "NOT-PDF"), r.status
    except Exception as e:  # noqa: BLE001
        return url, f"ERROR {type(e).__name__}", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--skip", action="store_true", help="skip network checks")
    args = ap.parse_args()

    urls: list[tuple[str, str]] = []
    for kind in ("books", "notes"):
        for m in read_manifests(kind):
            u = m.get("pdf_url", "")
            if u:
                urls.append((u, f"{kind}:{m['id']}"))

    if args.skip:
        print(f"skipping network checks ({len(urls)} urls)")
        return 0

    urls = urls[: args.limit] if args.limit else urls
    results: dict[str, tuple[str, str, int | None]] = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for u, tag in urls:
            results.setdefault(u, (u, "", None))
        # dedupe by url
        unique = sorted({u for u, _ in urls})
        futs = {pool.submit(check, u, args.timeout): u for u in unique}
        for fut in futs:
            u, status, code = fut.result()
            results[u] = (u, status, code)

    ok = bad = 0
    for u, tag in urls:
        _, status, code = results[u]
        if status == "PDF":
            ok += 1
        else:
            bad += 1
            print(f"BAD {tag}: {status} ({code}) {u}")
    print(f"urls checked: {len(urls)} (unique {len(unique)}), ok={ok}, bad={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())