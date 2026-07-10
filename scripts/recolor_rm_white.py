"""Recolor road-marking sources (svgs/RM_*.svg) from black to white.

Real road markings are white paint; the TPDM drawings use black. Two black
sources exist in these files: explicit stroke="#000000" and the implicit
default-black fill on paths without a fill attribute. The latter is fixed
by putting fill="#ffffff" on the root <g>, which children with explicit
fills (none / yellow / orange) override. Idempotent — rerunning is a no-op.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SVG_SRC = Path(__file__).resolve().parent.parent / "svgs"

ROOT_G = re.compile(r"<g\s(?![^>]*\bfill=)(?=[^>]*\btransform=)")


def main() -> int:
    changed = 0
    for svg in sorted(SVG_SRC.glob("RM_*.svg")):
        text = svg.read_text(encoding="utf-8")
        new = text.replace('stroke="#000000"', 'stroke="#ffffff"')
        # white default fill on the first (root) <g> only
        new = ROOT_G.sub('<g fill="#ffffff" ', new, count=1)
        if new != text:
            svg.write_text(new, encoding="utf-8")
            changed += 1
    print(f"{changed} RM SVGs recolored (of {len(list(SVG_SRC.glob('RM_*.svg')))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
