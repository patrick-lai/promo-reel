"""Box-wide heavy-work lock shared with Commission-ai's pre-merge cargo test gates.

Every heavy render (Live2D host layers, livestream compositing, `promo build` / `shot` / `mix` / `assemble` ffmpeg
work) holds `flock /tmp/commission-ai-cargo.lock` for its whole run, so a render and a cargo test gate never overlap.
Blocking: waits (logging every 30 s) until the lock is free. Re-entrant within one process (nested `heavy_lock()`
calls share the outer hold; a second flock on a new fd in the same process would deadlock).
Override the path with PROMO_HEAVY_LOCK (tests only).
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import sys
import time

DEFAULT = "/tmp/commission-ai-cargo.lock"
_depth = 0
_fd = None


def lock_path():
    return os.environ.get("PROMO_HEAVY_LOCK", DEFAULT)


def held():
    return _depth > 0


@contextlib.contextmanager
def heavy_lock(what="render", log=None):
    global _depth, _fd
    log = log or (lambda *a: print(*a, file=sys.stderr, flush=True))
    if _depth:
        _depth += 1
        try:
            yield
        finally:
            _depth -= 1
        return
    path = lock_path()
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o666)
    except PermissionError:
        fd = os.open(path, os.O_RDONLY)            # flock works on a read-only fd too
    t0 = time.time()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"[lock] {what}: waiting for {path} (a cargo test gate or another render holds it) ...")
        last = t0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(1.0)
                if time.time() - last >= 30:
                    last = time.time()
                    log(f"[lock] {what}: still waiting for {path} ({time.time() - t0:.0f} s)")
        log(f"[lock] {what}: acquired {path} after {time.time() - t0:.0f} s")
    _fd, _depth = fd, 1
    try:
        yield
    finally:
        _depth = 0
        _fd = None
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
