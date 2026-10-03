"""Stamps: content hashes of a step's inputs -> skip unchanged steps.

A stamp is build/stamps/<key>.json holding {digest, inputs}. `is_fresh(key, digest, outputs)` is true when the stored digest
matches and every output file exists. Digests combine: the relevant spec subtree, input files (sha for small files, size+mtime
for big ones), the source of the modules involved (incl. the project plugin file), and the render scale.
"""
from __future__ import annotations

import hashlib
import json
import os

PKG = os.path.dirname(os.path.abspath(__file__))


def file_sig(path):
    """sha256 for files < 1 MB, otherwise size+mtime_ns (cheap for multi-GB footage)."""
    if not path or not os.path.exists(path):
        return "missing"
    st = os.stat(path)
    if st.st_size < (1 << 20):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    return f"{st.st_size}:{st.st_mtime_ns}"


def code_hash(*modules, extra_files=()):
    """Hash the source of promo modules (names like 'render', 'shots/clip') plus extra files (project plugin)."""
    h = hashlib.sha256()
    for m in modules:
        p = os.path.join(PKG, m if m.endswith(".py") else m + ".py")
        h.update(open(p, "rb").read() if os.path.exists(p) else b"-")
    for p in extra_files:
        h.update(open(p, "rb").read() if os.path.exists(p) else b"-")
    return h.hexdigest()


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class Stamps:
    def __init__(self, build_dir):
        self.dir = os.path.join(build_dir, "stamps")

    def _p(self, key):
        return os.path.join(self.dir, key.replace("/", "_") + ".json")

    def get(self, key):
        try:
            with open(self._p(key)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def is_fresh(self, key, dig, outputs=()):
        s = self.get(key)
        return bool(s and s.get("digest") == dig and all(os.path.exists(o) for o in outputs))

    def write(self, key, dig, **info):
        os.makedirs(self.dir, exist_ok=True)
        with open(self._p(key), "w") as f:
            json.dump(dict(digest=dig, **info), f, indent=1)

    def mtime(self, key):
        try:
            return os.path.getmtime(self._p(key))
        except OSError:
            return None
