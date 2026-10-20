---
name: framefields-plates
description: Render procedural, UI-free video plates (aurora, smoke, dust, snow, sparks, light leaks) from code with framefields (gatewai-dev/framefields, Apache-2.0) on this Mac's GPU, deterministic and free, then register them as generated plates. Use when a promo needs an abstract background, a transition plate or a texture that must look the same on every render ("procedural background", "aurora background", "particle background", "framefields"). A helper next to promo-reel; AGENTS.md rules 1-5 win.
---

# framefields-plates

framefields is a code-first video SDK that renders a TypeScript `Composition` on native WebGPU (Metal here) in Node.
promo-reel uses it for one thing: abstract plates with no text, no logos and no UI, made in seconds and identical on every run.
Nothing of framefields lives in this repo. Install it in a scratch folder outside the repo, render there, and bring back only the mp4.
It does not replace `promo gen` (prompted generative clips). It covers procedural looks that a prompt cannot pin down frame for frame.

Upstream, pinned: npm `framefields@2.3.2` (repo commit `4a26e73`, 2026-10-19; beta, expect API churn). Its own skills
(`plugins/framefields/skills/framefields-compose/SKILL.md`, "Procedural VFX") document every effect and knob.

## Set up once (about 15 s, 800 MB of node_modules, outside the repo)
```sh
mkdir -p ~/.promo-reel/tools/framefields-plates/src && cd ~/.promo-reel/tools/framefields-plates
cat > package.json <<'EOF'
{ "name": "framefields-plates", "private": true, "type": "module",
  "allowScripts": { "skia-canvas": true, "sharp": false, "webgpu": false, "onnxruntime-node": false, "node-av": false, "esbuild": false },
  "trustedDependencies": ["skia-canvas"] }
EOF
npm install framefields@2.3.2 tsx@4 --no-audit --no-fund
```
Node 22 or newer. `skia-canvas` is the one install script framefields needs. Never approve every script. npm may warn about
`protobufjs`'s postinstall: leave it unapproved, plates render without it.

## Render a plate
`src/plate.ts`:
```ts
import { Composition, Layer } from "framefields";

// tsx src/plate.ts OUT.mp4 EFFECT SECONDS WIDTH HEIGHT FPS SEED COLOR_START COLOR_END SCALE DENSITY
const [out, effectType = "Aurora", seconds = "4", w = "1920", h = "1080", fps = "30", seed = "7", colorStart = "#2bff88", colorEnd = "#7a3cff", scale = "0.01", density = "0.7"] = process.argv.slice(2);
const W = +w, H = +h;
const film = new Composition({ width: W, height: H, fps: +fps, durationMs: +seconds * 1000, backgroundColor: "#05060d" });
film.add(Layer.vfx({ effectType: effectType as "Aurora", width: W, height: H, colorStart, colorEnd, density: +density, scale: +scale, intensity: 1, speed: 1, seed: +seed }));

const result = await film.renderVideo({ outputPath: out, quality: "high" });
await result.cleanup?.();
process.exit(0);   // native WebGPU threads keep the process alive otherwise
```
```sh
./node_modules/.bin/tsx src/plate.ts /tmp/aurora-raw.mp4 Aurora 6 1920 1080 30 7 "#2bff88" "#7a3cff"
ffmpeg -v error -y -i /tmp/aurora-raw.mp4 -an -c:v copy <project>/media/aurora.mp4     # renderVideo always adds a silent AAC track
```
- Match the project: `output.fps`, 1920x1080 (3840x2160 for a `--scale 2` master), and at least the shot's length plus the `t_in` you use.
- `effectType`: Smoke, Fire, Rain, Sparks, Snow, Dust, Lightning, Magic, LensFlare, Embers, EnergyBeam, Aurora. Stack several `Layer.vfx`
  layers for depth (an Aurora with a Dust layer over it). For particles that follow forces, use `Layer.particles` (upstream compose skill).
- Change only `seed` to get a sibling plate. The same script and seed give the same frames.

## Bring it into the project
```sh
promo gen register <project>/media/aurora.mp4 -p <project>/promo.yaml --id plate-aurora --provider local:framefields \
  --prompt "framefields 2.3.2 Layer.vfx Aurora #2bff88->#7a3cff seed 7, 6 s 1080p30" --shots 05
```
Put the whole recipe in `--prompt` (version, effect, colours, scale, density, seed) so the plate can be made again. Then use
`source: plate-aurora` on a shot with `ui: false`. `promo check` treats it like any generated plate: `generated-plates` FAILs it on a
UI shot and `generated-review` WARNs until a person has looked.

## Look before you use it
`ffmpeg -i plate.mp4 -vf "select='eq(n\,0)+eq(n\,90)+eq(n\,179)',scale=640:-1,tile=3x1" -frames:v 1 strip.png`, then open
the strip. Measured on this Mac (20 Oct 2026): a 4-6 s 1080p30 plate renders in 1.3-3.8 s, and two renders of one script decode
to identical frames (framemd5).

## Pitfalls
- Smoke at the default `scale` 0.01 renders almost nothing (its puffs only show when the noise is fine enough). Use scale ≈ 0.03 and
  density 1 with light colours. Aurora reads well at the defaults.
- Light effects are drawn on the composition background. Keep it near black (`#05060d`) and grade the plate in the shot, not in framefields.
- Never add `Layer.text`, logos, screenshots or anything that reads as the product: a plate stays text-free and UI-free (rule 1).
- Keep the scratch folder, node_modules and renders out of the repo. Only the registered mp4 path goes into the footage manifest.

## Rules here
- Plates only: `ui: false` shots, `generated:` on the manifest entry (`promo gen register` writes it), never captioned as the product (rule 3).
- No sound from framefields (rule 4): the plate's track is removed, and promo-reel's mix stays the only soundtrack.
- framefields' render worker and cloud options are not used: everything renders on this Mac and nothing is published (rule 5).
