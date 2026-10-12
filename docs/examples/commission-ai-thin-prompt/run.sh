#!/usr/bin/env bash
# Thin-prompt e2e for commission-ai: prompt + three stills -> designed plan -> previz strip -> quick look -> 540p draft -> check.
# Dialect: ethereal (also the default for this prompt). Craft-note captions; the end card is the team default unless another ask is given.
# Review rounds stay 540p first. Nothing here uploads or posts anything.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="${1:-commission-thin}"
PROMPT="$(cat "$HERE/prompt.txt")"
mapfile -t STILLS < <(grep -v '^#' "$HERE/stills.txt" | sed '/^$/d')

promo plan "$NAME" --prompt "$PROMPT" --stills "${STILLS[@]}" \
  --dialect ethereal --default cta="Your AI dev crew, on your Mac."

promo cospec "$NAME"                  # at most three optional questions: end card (GitHub vs landing), the one promise, the audience
# promo cospec "$NAME" --answer cta="<exact words>" --answer promise="Wake up to merged PRs" --answer audience="<who>"

promo designed apply "$NAME"          # cinema shots into promo.yaml; stills registered in the footage manifest
promo -p "$NAME" previz build && promo -p "$NAME" previz strip   # wireframe the camera / panels / type first: look at previz/strip.png, nudge with `promo previz cam|panel|type|dur ... --strip`
promo -p "$NAME" --scale 0.5 build --look && promo -p "$NAME" strip --out "$NAME-strip.png"   # post the strip first

promo gen plan -p "$NAME"             # plate prompts (non-UI): make each, `promo gen register`, then re-run `promo designed apply`

# A 540p draft needs a music asset (licensed bed in assets.yaml; `test_only: true` for an internal test only).
promo -p "$NAME" preview
promo -p "$NAME" check
