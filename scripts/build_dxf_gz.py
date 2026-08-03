"""Build site/dxfs/*.dxf.gz alongside the DXFs, for the download path to inflate.

GitHub Pages gzips what it serves, but only for a whitelist of content types.
DXF is not on it: the files go out as image/vnd.dxf with no content-encoding at
all, so TS_2714 costs a visitor 924 KB. DXF is plain ASCII and compresses about
8x, and Pages gives no way to set response headers, so the compression has to
be baked into a file the page fetches and inflates itself.

The plain .dxf stays next to it. It is what direct links, the README, and any
visitor without DecompressionStream still get, and the gz is only an
optimization layered on top by assets/dxf-download.js.

Rerunnable: .gz files newer than their .dxf are skipped (use --force to redo
everything).
"""

from __future__ import annotations

import argparse
import gzip
import io
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DXFS = ROOT / "site" / "dxfs"


def _compress(path_str: str) -> tuple[str, int, int, str]:
    """Worker: gzip one DXF. Returns (name, raw_bytes, gz_bytes, error)."""
    dxf = Path(path_str)
    try:
        raw = dxf.read_bytes()
        # Normalized to LF because that is what gets served: the repo stores
        # these with LF, and a Windows checkout turns them into CRLF locally.
        # Compressing the working copy as-is would make the inflated download
        # differ from the plain .dxf behind the same button - same drawing,
        # 924,700 bytes against 767,284 - and pad the .gz with 157,416
        # carriage returns nobody asked for.
        raw = raw.replace(b"\r\n", b"\n")
        buf = io.BytesIO()
        # mtime=0 and no embedded filename: the output depends only on the
        # input, so an unchanged DXF re-gzips to identical bytes and does not
        # show up as a spurious change in git.
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
            fh.write(raw)
        out = buf.getvalue()
        dxf.with_suffix(".dxf.gz").write_bytes(out)
        return dxf.name, len(raw), len(out), ""
    except Exception as exc:
        return dxf.name, 0, 0, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="recompress everything")
    ap.add_argument("--jobs", type=int, default=None, help="parallel workers")
    args = ap.parse_args(argv)

    dxfs = sorted(SITE_DXFS.glob("*.dxf"))
    if not dxfs:
        print(f"no .dxf files in {SITE_DXFS}", file=sys.stderr)
        return 1

    todo = []
    for dxf in dxfs:
        gz = dxf.with_suffix(".dxf.gz")
        if args.force or not gz.exists() or gz.stat().st_mtime < dxf.stat().st_mtime:
            todo.append(str(dxf))

    print(f"{len(dxfs)} DXFs, {len(todo)} to compress")
    failures: dict[str, str] = {}
    raw_total = gz_total = 0
    if todo:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            done = 0
            for fut in as_completed(pool.submit(_compress, t) for t in todo):
                name, raw, gz, err = fut.result()
                done += 1
                if err:
                    failures[name] = err
                    print(f"FAIL  {name}: {err}", file=sys.stderr)
                else:
                    raw_total += raw
                    gz_total += gz
                if done % 200 == 0:
                    print(f"  ... {done}/{len(todo)}")

    # A .gz whose .dxf is gone would be served to nobody and downloaded by
    # nobody, but it would still sit in the repo.
    stale = [
        p for p in SITE_DXFS.glob("*.dxf.gz") if not p.with_suffix("").exists()
    ]
    for p in stale:
        p.unlink()

    built = len(list(SITE_DXFS.glob("*.dxf.gz")))
    print(f"{built} .dxf.gz files, {len(stale)} stale removed, {len(failures)} failures")
    if raw_total:
        print(
            f"compressed {raw_total / 1048576:.1f} MB -> {gz_total / 1048576:.1f} MB "
            f"({raw_total / max(gz_total, 1):.1f}x smaller)"
        )
    if failures:
        for name, err in sorted(failures.items()):
            print(f"  FAILED: {name}: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
