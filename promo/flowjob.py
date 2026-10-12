"""Live progress of a long flow step (storyboard frames, asset samples, `promo build`) in `flow/job.json`.

Generating 20 frames takes ten minutes or more, and the person cannot see the agent's tools. The job record lets the Stage and the chat card show a
count that goes up, each picture as it lands, what is being made right now, and a run that died half way (its process is gone but it never finished).
"""
from __future__ import annotations

import datetime
import json
import os
import threading

FILE = "job.json"
ITEMS_MAX = 48
HEARTBEAT_S = 60        # a shot can render for minutes: `updated` keeps moving while the process lives, so the Stage can tell slow from dead
BUILD_BEAT_S = 20       # a build's `now` (which shot, how far) moves on its own, so it is written more often
STILL_GAP_S = 3         # new stills wake the heartbeat at once, but publish at most this often (a quick look lands dozens a minute)
NOUN = dict(frames=("image", "images"), samples=("sample", "samples"), build=("step", "steps"), plates=("plate", "plates"))


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(fd):
    p = os.path.join(fd, FILE)
    return json.load(open(p)) if os.path.isfile(p) else None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def state(job):
    """running | done | stopped (ended early, or its process is gone without finishing)."""
    if job.get("finished"):
        return "stopped" if job.get("stopped") else "done"
    return "running" if alive(job["pid"]) else "stopped"


class Job:
    """One run. `queue` is every item in the order the worker pool takes them ([{id, label, ...}]); a pool of `workers` takes them first in, first
    out, so the ones being made right now are the first `workers` unfinished ones, with no start events to track.
    `on_change` (the live publish) runs after every write, under the lock, so two finished items never publish out of order."""

    def __init__(self, fd, kind, label, queue, workers, on_change=None, resume=None, beat_s=HEARTBEAT_S):
        self.fd, self.workers, self.on_change, self.beat_s = fd, max(1, workers), on_change, beat_s
        self.queue = list(queue)
        self.lock = threading.Lock()
        self.d = dict(kind=kind, label=label, total=len(self.queue), done=0, failed=0, started=_now(), updated=_now(), finished=None, stopped=False,
                      pid=os.getpid(), waiting=None, resume=resume, active=[], items=[], now=None, strip=None)
        self._stop, self._poke = threading.Event(), threading.Event()
        with self.lock:
            self._write()
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self):
        while True:
            poked = self._poke.wait(self.beat_s)
            self._poke.clear()
            if self._stop.is_set():
                return
            with self.lock:
                self._write()
            if poked and self._stop.wait(STILL_GAP_S):
                return

    def preview(self, now):
        """What the item being made looks like right now: {id, label, frac} and, with a new still, {which, still, strip, look}. Called from the
        render loop, so it never takes the lock or publishes (a publish can block for minutes): it swaps in a new dict and the heartbeat writes it,
        woken at once when a still landed."""
        cur = self.d["now"] if (self.d["now"] or {}).get("id") == now["id"] else {}
        cur = dict(cur, **{k: v for k, v in now.items() if v is not None}, at=_now())
        if now.get("strip"):
            self.d["strip"] = now["strip"]
        self.d["now"] = cur
        if now.get("still"):
            self._poke.set()

    def _write(self):
        finished = {x["id"] for x in self.d["items"]}
        self.d["active"] = [] if self.d["finished"] else [q for q in self.queue if q["id"] not in finished][:self.workers]
        self.d["updated"] = _now()
        os.makedirs(self.fd, exist_ok=True)
        tmp = os.path.join(self.fd, FILE + ".tmp")
        with open(tmp, "w") as f:
            json.dump(self.d, f, indent=1)
        os.replace(tmp, os.path.join(self.fd, FILE))
        if self.on_change:
            self.on_change()

    def item(self, iid, path, error, skipped=False):
        """An item finished: `path` is the file it made (absolute), `error` the reason when it failed, `skipped` = already up to date."""
        meta = next((q for q in self.queue if q["id"] == iid), dict(id=iid, label=iid))
        with self.lock:
            self.d["failed" if error else "done"] += 1
            self.d["now"] = None                      # the next shot's first still brings it back; a mix step has no picture of its own
            self.d["items"].append(dict(meta, at=_now(), ok=not error, skipped=skipped, path=None if error else path, error=(error or "")[:200] or None))
            del self.d["items"][:-ITEMS_MAX]
            self._write()

    def wait(self, why):
        """Not started yet, and why (another render holds the box-wide lock); None once it runs."""
        with self.lock:
            if self.d["waiting"] != why:
                self.d["waiting"] = why
                self._write()

    def close(self, stopped=False, error=None):
        """`error`: the item being made when the run broke failed with it (a build step that raised)."""
        with self.lock:
            cur = self.d["active"][:1]
            if error and cur:
                self.d["failed"] += 1
                self.d["items"].append(dict(cur[0], at=_now(), ok=False, skipped=False, path=None, error=str(error)[:200]))
            self.d.update(finished=_now(), stopped=stopped, waiting=None, now=None)
            self._write()
        self._stop.set()
        self._poke.set()
