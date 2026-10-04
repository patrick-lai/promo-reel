"""Hero v3 (v2 + float_window support): measure every on-screen text a caption or VO line names, with promo check's named-element measurement
(promo/named.py: ascender-top -> baseline ink height x effective scale, 1080p). Run from the repo root:
    python projects/commission-ai-hero/tools/named_v3.py [--json out.json]
Each row: shot, name, box (source px of the clip), shot-local output times to measure at, min px (18 = gate), ink thr.
Rows with min 0 are informational (text the claim relies on indirectly, reported but not gated)."""
import json
import sys

sys.path.insert(0, ".")
from promo import named as N           # noqa: E402
from promo import render as R          # noqa: E402
from promo.spec import load_spec as load, resolve_cam_keys   # noqa: E402
from promo.shots.clip import segments  # noqa: E402

SPEC = "projects/commission-ai-hero/promo.yaml"
ROWS = [
    # shot, name, box [x0, y0, x1, y1] (source px), output t list, min_px, thr, why
    ("04", "card id 'PAY-103' (8-card count)", [40, 186, 140, 206], [3.5, 5.4], 0, 90, "caption 'Split into 8 tasks.': the count is the 8 cards, ids shown for size"),
    ("04", "Wave 1 '4 tickets'", [337, 75, 416, 94], [3.5, 5.4], 0, 90, "caption 'Split into 8 tasks.' (4 + 3 + 1 tickets)"),
    ("08", "status line 'Running checks'", [482, 358, 692, 383], [0.6, 2.4], 18, 100, "VO 'run the checks'"),
    ("08", "chip 'Checks'", [936, 523, 1029, 546], [0.6, 2.4], 18, 110, "VO 'run the checks'"),
    ("10", "PAY-106 chip 'Needs you'", [1129, 845, 1238, 868], [1.0, 2.5, 3.4], 18, 110, "VO 'when it needs you'"),
    ("12", "reviewer line 'Approved. ... matches the plan ...'", [20, 469, 1695, 502], [1.2, 3.0, 6.0], 18, 110, "VO 'tells you why it passes' / caption 'Reviewed, with the reason why.'"),
    ("11", "header '8 in this run · 8 landed'", [849, 47, 1103, 77], [0.2, 1.3, 2.4], 18, 110, "caption '8 TASKS · ALL MERGED'"),
    ("11", "column title 'Landed'", [1500, 285, 1600, 310], [0.2, 1.3, 2.4], 18, 110, "caption '... ALL MERGED' (Landed = merged)"),
    ("11", "column sub-title 'Merged and closed'", [1500, 317, 1672, 339], [0.2, 1.3, 2.4], 0, 90, "the literal word 'Merged' in the caption frame (informational)"),
    ("15", "PR badge 'Merged' (float window)", [855, 472, 926, 496], [1.9, 2.8, 3.6], 0, 110, "S15 has no caption/VO naming it in v3 (VO 'Go to bed.' only); measured to show why the line moved to S16"),
    ("16", "PR badge 'Merged'", [315, 428, 412, 456], [0.7, 1.5, 2.4], 18, 110, "VO 'Wake up to merged PRs.' lands on the flip"),
]


def main():
    spec = load(SPEC)
    shots = {s.id: s for s in spec.shots}
    out, fails = [], 0
    for sid, name, box, ts, mn, thr, why in ROWS:
        s = shots[sid]
        total = s.n / spec.fps
        if s.cfg.get("type") == "float_window":     # window pixels = output pixels; camera A (== B here) on the source
            ww, wh = s.cfg["window"]
            for t in ts:
                st = s.cfg["t_in"] + t
                cam = R.cam_at(s.cfg["camA"], t)
                r = N.element_px(N.gray_frame(spec.footage_path(s.cfg["source"]), st), tuple(cam[:3]), (ww, wh), box, thr=thr)
                px = r["px"] if r else None
                ok = (px is not None and px >= mn and r["inside"]) if mn else True
                fails += 0 if ok else 1
                out.append(dict(shot=sid, name=name, t=t, src_t=round(st, 3), cam=[round(c, 4) for c in cam[:3]], px=px,
                                src_px=r["src"] if r else None, scale=r["scale"] if r else None, inside=r["inside"] if r else None,
                                min_px=mn, status="PASS" if (ok and mn) else ("INFO" if not mn else "FAIL"), why=why))
                print(f"{out[-1]['status']:4s} {sid:>3s} t={t:4.2f} src={st:5.2f} {name:48s} {px} px (src {out[-1]['src_px']} x {out[-1]['scale']}) inside={out[-1]['inside']}")
            continue
        segs = segments(s)
        keys = resolve_cam_keys(s.cfg["cam"], total)
        for t in ts:
            acc = 0
            for sg in segs:
                if t <= acc + sg["dur"] + 1e-6:
                    break
                acc += sg["dur"]
            u = (t - acc) / sg["dur"]
            st = sg["t_in"] + (sg["t_out"] - sg["t_in"]) * u
            cam = R.cam_at(resolve_cam_keys(sg["cam"], sg["dur"]), t - acc) if sg.get("cam") else R.cam_at(keys, t)
            path = spec.footage_path(sg.get("source", s.cfg.get("source")))
            fr = N.gray_frame(path, st)
            r = N.element_px(fr, tuple(cam[:3]), (1920, 1080), box, thr=thr)
            px = r["px"] if r else None
            ok = (px is not None and px >= mn and r["inside"]) if mn else True
            fails += 0 if ok else 1
            out.append(dict(shot=sid, name=name, t=t, src_t=round(st, 3), cam=[round(c, 4) for c in cam[:3]], px=px,
                            src_px=r["src"] if r else None, scale=r["scale"] if r else None, inside=r["inside"] if r else None,
                            min_px=mn, status="PASS" if (ok and mn) else ("INFO" if not mn else "FAIL"), why=why))
            print(f"{out[-1]['status']:4s} {sid:>3s} t={t:4.2f} src={st:5.2f} {name:48s} {px} px (src {out[-1]['src_px']} x {out[-1]['scale']}) inside={out[-1]['inside']}")
    if "--json" in sys.argv:
        json.dump(dict(min_px=N.MIN_NAMED_PX, rows=out, fails=fails), open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1, ensure_ascii=False)
    print("named FAILs:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
