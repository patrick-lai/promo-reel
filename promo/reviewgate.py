"""Review rounds for a project `promo plan` filled in (docs/PRODUCT-DEFAULTS.md).

`promo preview` is 540p plus stills. One feedback file per round (`reviews/round-N.md`) has a list and a
`signed-off:` slot for Marketing, Zen and Director. `promo build --final`, and any render above 540p, refuses
until all three have signed and no beat is empty. Three rounds, then the cut goes to Patrick.

A project with no `plan.review.required` is not gated (existing specs keep building at 1080).
"""
from __future__ import annotations

import os
import re
import subprocess

from .spec import SpecError

ROLES = ("Marketing", "Zen", "Director")
MAX_ROUNDS = 3
NOT_SIGNED = {"", "no", "n", "false", "pending", "todo", "tbd"}
BEATS = ("hook", "problem", "demo", "payoff", "cta")


class ReviewError(SpecError):
    pass


def _raw(spec):
    """A loaded spec has `raw`. A caller that only hands dispatch a stand-in (flow's build reporter) does not, and is not a planned project."""
    raw = getattr(spec, "raw", None)
    return raw if isinstance(raw, dict) else {}


def _plan(spec):
    return _raw(spec).get("plan") or {}


def review_on(spec):
    review = _raw(spec).get("review") or _plan(spec).get("review") or {}
    return bool(review.get("required"))


def empty_beats(spec):
    beats = _plan(spec).get("beats") or {}
    if not beats and not review_on(spec):
        return []
    if not beats:
        return list(BEATS)
    return [k for k in BEATS if not str(beats.get(k) or "").strip()]


def reviews_dir(root):
    return os.path.join(root, "reviews")


def round_numbers(root):
    d = reviews_dir(root)
    if not os.path.isdir(d):
        return []
    nums = []
    for name in os.listdir(d):
        m = re.fullmatch(r"round-(\d+)\.md", name)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def round_path(root, n):
    return os.path.join(reviews_dir(root), f"round-{n}.md")


def feedback_template(n):
    parts = [f"# Round {n}", ""]
    for role in ROLES:
        parts += [f"## {role}", "", "-", "", "signed-off:", ""]
    return "\n".join(parts).rstrip() + "\n"


def ensure_round(root, n=1):
    """Write reviews/round-<n>.md if it is missing. Does not overwrite a file the human has edited."""
    path = round_path(root, n)
    if os.path.isfile(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(feedback_template(n))
    return path


def new_round(spec):
    nums = round_numbers(spec.root)
    n = (nums[-1] + 1) if nums else 1
    if n > MAX_ROUNDS:
        raise ReviewError(f"{MAX_ROUNDS} rounds used; hand this to Patrick")
    return ensure_round(spec.root, n)


def parse_signoffs(text):
    """{role: {signed_off, lines}} from a feedback file. Roles are the ## headings."""
    roles, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip()
            roles.setdefault(current, {"signed_off": "", "lines": []})
            continue
        m = re.match(r"^signed-off:\s*(.*)$", line, re.I)
        if m and current:
            roles[current]["signed_off"] = m.group(1).strip()
            continue
        if current and line.strip() and not line.startswith("#"):
            roles[current]["lines"].append(line.strip())
    return roles


def missing_signoffs(text):
    roles = parse_signoffs(text)
    missing = []
    for role in ROLES:
        val = (roles.get(role) or {}).get("signed_off", "")
        if val.strip().lower() in NOT_SIGNED:
            missing.append(role)
    return missing


def _over_rounds(root):
    nums = round_numbers(root)
    return bool(nums) and (len(nums) > MAX_ROUNDS or max(nums) > MAX_ROUNDS)


def check_build(spec, final=False, scale=None):
    """Raise ReviewError when this render is not allowed. Returns None when it is.

    `--final` always refuses empty beats when the project has a `plan.beats` map (or review is required).
    Above 540p, a planned project also needs `--final` and all three sign-offs. Preview scale 0.5 does not.
    """
    scale = float(spec.scale if scale is None else scale)
    if final:
        empty = empty_beats(spec)
        if empty:
            raise ReviewError("refusing --final: empty beats: " + ", ".join(empty))
    if not review_on(spec):
        return None
    above = scale > 0.5 + 1e-9
    if (final or above) and _over_rounds(spec.root):
        raise ReviewError(f"{MAX_ROUNDS} rounds used; hand this to Patrick")
    if above and not final:
        raise ReviewError("anything above 540p needs `promo build --final` after Marketing, Zen and Director sign off")
    if not final:
        return None
    nums = round_numbers(spec.root)
    if not nums:
        raise ReviewError("refusing --final: no reviews/round-N.md sign-off (Marketing, Zen, Director)")
    missing = missing_signoffs(open(round_path(spec.root, nums[-1])).read())
    if missing:
        raise ReviewError("refusing --final: not signed off: " + ", ".join(missing))
    return None


def assert_preview_scale(spec):
    if abs(float(spec.scale) - 0.5) > 1e-9:
        raise ReviewError("promo preview is 540p and stills only")


def write_stills(spec):
    """One JPEG per shot from the 540p master, plus the contact sheet path when that build wrote one. No 1080."""
    from . import contact
    dest = os.path.join(spec.out, "preview-stills")
    os.makedirs(dest, exist_ok=True)
    paths = []
    video = spec.output_path(spec.masters[0].get("suffix", "")) if spec.masters else None
    if video and os.path.isfile(video):
        for s in spec.shots:
            t = float(s.t0) + min(0.4, float(s.dur) / 2)
            jpg = os.path.join(dest, f"{s.id}.jpg")
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-q:v", "4", jpg],
                               capture_output=True, text=True)
            if r.returncode == 0 and os.path.isfile(jpg):
                paths.append(jpg)
    sheet = contact.contact_paths(spec)[0]
    if os.path.isfile(sheet):
        paths.append(sheet)
    return paths


def status(spec):
    nums = round_numbers(spec.root)
    missing, latest = list(ROLES), None
    if nums:
        latest = nums[-1]
        missing = missing_signoffs(open(round_path(spec.root, latest)).read())
    empty = empty_beats(spec)
    ready = review_on(spec) and not missing and not empty and not _over_rounds(spec.root)
    lines = [
        f"review {'on' if review_on(spec) else 'off (legacy project)'}",
        f"rounds: {nums or 'none'} (max {MAX_ROUNDS})",
        f"sign-off: {('missing ' + ', '.join(missing)) if missing else 'Marketing, Zen, Director'}",
        f"beats: {('empty ' + ', '.join(empty)) if empty else 'filled'}",
        "ready for promo build --final" if ready else "not ready for a final",
    ]
    if _over_rounds(spec.root):
        lines.append(f"{MAX_ROUNDS} rounds used; hand this to Patrick")
    return dict(ok=True, ready=ready, rounds=nums, latest=latest, missing_signoffs=missing, empty_beats=empty,
                max_rounds=MAX_ROUNDS, summary="\n".join(lines))
