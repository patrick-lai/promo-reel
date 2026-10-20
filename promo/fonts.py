"""Fonts by the path the presets and projects name. `promo fonts fetch | list`.

The presets name Google fonts by their place in the Linux image promo-reel grew up on (/usr/share/fonts/truetype/sand-box/google/...)
and DejaVu by its Debian path. Where such a path does not exist (a Mac cannot write under /usr/share), the same file is looked for
under ~/.promo-tools/fonts/<google|dejavu>/<same relative path>. `promo fonts fetch` fills that folder once, from the fonts' own
releases with their licence files beside them: Inter and Barlow Condensed (SIL Open Font License 1.1, github.com/google/fonts) and
DejaVu (Bitstream Vera licence, github.com/dejavu-fonts). A path that exists is used as it is, so a Linux box is unchanged.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

LOCAL = Path.home() / ".promo-tools" / "fonts"
MAPS = (("/usr/share/fonts/truetype/sand-box/google/", "google/"), ("/usr/share/fonts/truetype/google/", "google/"),
        ("/usr/share/fonts/truetype/dejavu/", "dejavu/"))
GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
GOOGLE_FILES = {                                    # local relative path -> file in github.com/google/fonts
    "google/Inter/Inter-VariableFont_opsz,wght.ttf": "inter/Inter%5Bopsz,wght%5D.ttf",
    "google/Inter/OFL.txt": "inter/OFL.txt",
    **{f"google/Barlow Condensed/BarlowCondensed-{s}.ttf": f"barlowcondensed/BarlowCondensed-{s}.ttf"
       for s in ("Black", "BlackItalic", "BoldItalic", "SemiBoldItalic")},
    "google/Barlow Condensed/OFL.txt": "barlowcondensed/OFL.txt",
}
DEJAVU_ZIP = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip"
DEJAVU_FILES = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSerif.ttf", "DejaVuSansMono.ttf")


def path(p):
    """`p` when it exists, else the same font under ~/.promo-tools/fonts when that is there, else `p` (the caller's error names it)."""
    if not p or os.path.exists(p):
        return p
    for prefix, sub in MAPS:
        if p.startswith(prefix):
            alt = LOCAL / sub / p[len(prefix):]
            if alt.exists():
                return str(alt)
    return p


def wanted():
    return [LOCAL / rel for rel in GOOGLE_FILES] + [LOCAL / "dejavu" / f for f in DEJAVU_FILES + ("LICENSE",)]


def _get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def fetch(log=print):
    """Download whatever of `wanted()` is missing. Returns the number of files written."""
    n = 0
    for rel, src in GOOGLE_FILES.items():
        dest = LOCAL / rel
        if dest.exists():
            continue
        data = _get(GOOGLE + src)
        if rel.endswith(".ttf") and data[:4] not in (b"\x00\x01\x00\x00", b"true"):
            raise RuntimeError(f"{GOOGLE + src} is not a TrueType font")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log(f"  {rel}")
        n += 1
    missing = [f for f in DEJAVU_FILES + ("LICENSE",) if not (LOCAL / "dejavu" / f).exists()]
    if missing:
        with zipfile.ZipFile(io.BytesIO(_get(DEJAVU_ZIP))) as z:
            names = {os.path.basename(m): m for m in z.namelist()}
            for f in missing:
                dest = LOCAL / "dejavu" / f
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(names[f]))
                log(f"  dejavu/{f}")
                n += 1
    return n


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "fetch":
        try:
            n = fetch()
        except (OSError, RuntimeError, KeyError) as e:
            print(f"promo fonts fetch: {e}", file=sys.stderr)
            return 2
        print(f"{n} font file(s) written to {LOCAL}" if n else f"all fonts already in {LOCAL}")
        return 0
    if cmd == "list":
        for p in wanted():
            print(f"{'ok     ' if p.exists() else 'missing'} {p}")
        return 0
    print("promo fonts fetch | list", file=sys.stderr)
    return 2
