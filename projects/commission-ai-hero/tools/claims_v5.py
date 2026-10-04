"""SUPERSEDED (integrate/v1): `promo check` now runs this for every project (generic `claims` gate,
promo/generic_check.py). Kept as the v5 record.

Hero v5: run promo check's claims audit (promo.claims.audit, the same function the anime-opening `claims` gate runs) on the
hero spec, and assert the S11 caption equals the selected claims.landed_count row. The hero spec has no style preset, so
`promo check` does not run the claims gate itself (it lives in style_check.anime_gates). Run from the repo root:
    python projects/commission-ai-hero/tools/claims_v5.py [--json out.json]"""
import json
import sys

sys.path.insert(0, ".")
from promo import claims as C          # noqa: E402
from promo.spec import load_spec       # noqa: E402

spec = load_spec("projects/commission-ai-hero/promo.yaml")
res = C.audit(spec.raw, spec.resolve)
text, info = C.resolve(spec.raw, "claims.landed_count")
cap = [o["text"] for s in spec.shots if s.id == "11" for o in (s.cfg.get("overlays") or []) if o.get("type") == "caption"]
ev = info and spec.raw["claims"]["tables"]["landed_count"]["evidence"]
mc = C.manifest_counts(ev["manifest"], ev["section"])
rows = [dict(status=st, msg=m) for st, m in res]
ok_cap = cap == [text]
rows.append(dict(status="PASS" if ok_cap else "FAIL", msg=f"S11 caption {cap} == claims.landed_count {text!r} (legible {info['legible']}, manifest counts {mc})"))
for r in rows:
    print(f"{r['status']:4s}  {r['msg']}")
fails = sum(r["status"] == "FAIL" for r in rows)
print("claims FAILs:", fails)
if "--json" in sys.argv:
    json.dump(dict(rows=rows, selected=text, legible=info["legible"], manifest_counts=mc, fails=fails),
              open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1, ensure_ascii=False)
sys.exit(1 if fails else 0)
