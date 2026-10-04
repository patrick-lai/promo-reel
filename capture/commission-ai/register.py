#!/usr/bin/env python3
# Registers every v1-1080 clip in notes.json with promo-reel's footage manifest (promo footage add).
import json, os, subprocess, sys, yaml
HERE = os.path.dirname(os.path.abspath(__file__))
D = "/workspace/videos/commission-ai-promo/footage/v1-1080"
PY = "/workspace/videos/commission-ai-promo/.venv/bin/python"
REPO = "/workspace/promo-reel"; PROJ = "projects/commission-ai-hero/promo.yaml"
COMMIT = "4a427fc05f829d7b2e4ed7ea642d77340554f7f8"
notes = json.load(open(f"{HERE}/notes.json"))
log = [json.loads(l) for l in open(f"{D}/capture-log.jsonl")]
have = {c["id"]: c for c in (yaml.safe_load(open(f"{REPO}/projects/commission-ai-hero/footage/manifest.yaml")) or {}).get("clips", [])}
only = sys.argv[1:]
for n in notes["clips"]:
    f = f"{D}/{n['file']}.mov"; cid = n.get("id", n["file"] + "-v1080")
    if not os.path.exists(f) or (only and cid not in only): continue
    at = next((e["at"] for e in reversed(log) if e.get("shot") == n["file"]), None)
    cmd = [PY, "-m", "promo", "-p", PROJ, "footage", "add", f, "--id", cid, "--shots", *n["shots"], "--commit", n.get("commit", COMMIT),
           "--capture", n["url"].strip("`") + (" ; " + n["capture_extra"] if n.get("capture_extra") else ""), "--framing", n["framing"],
           "--dpr", str(n.get("dpr", 1)), "--notes", (n["beat"] + " || " + n["notes"]).replace("`", "'"), "--demo", "--json"]
    if at: cmd += ["--captured-at", at]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    print(cid, "rc", r.returncode, r.stdout.strip()[:300], r.stderr.strip()[-300:] if r.returncode else "")
