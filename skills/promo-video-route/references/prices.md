# Credit math (as of 2026-10-06)

Re-check before a paid batch:

- [runway.com/pricing](https://runway.com/pricing)
- [docs.dev.runwayml.com/guides/pricing](https://docs.dev.runwayml.com/guides/pricing) (API credits at $0.01 each; app-plan credits are a separate balance)
- Higgsfield pricing page and [AI video credits explained](https://higgsfield.ai/blog/ai-video-credits-explained)
- Higgsfield MCP: every generation through MCP/CLI deducts credits ([connect guide](https://higgsfield.ai/creator-hub/help-center/integrations/how-do-i-connect-higgsfield-to-ai-agent))

Prefer the connector's live quote for the job you are about to run. Higgsfield plan cards have moved between $15/200, $19/270, $49/1000 and $59/1200 in 2026; the **relative** ranking below is the useful part.

## What one 4 s 720p plate costs (approx.)

App-plan dollars assume the credits are used up that month.

| Model | Higgsfield credits (720p) | Higgsfield Plus ~$0.05/credit | Runway credits | Runway Pro ($35 / 2250 cr ≈ $0.016/cr) | Runway API ($0.01/cr) |
|---|---|---|---|---|---|
| Kling 3.0 | ~8 / 4 s (10 / 5 s) | ~$0.40 | ~13/s with audio → 52 | ~$0.81 | — |
| Wan 2.7 | ~6 / 4 s (8 / 5 s) | ~$0.32 | — | — | — |
| Gen-4 Turbo | — | — | 5/s → 20 | ~$0.31 | $0.20 |
| Gen-4.5 | — | — | 12/s → 48 | ~$0.75 | $0.48 |
| Cinema Studio | ~20 / 4 s (25 / 5 s) | ~$1.00 | — | — | — |
| Seedance 2.0 | ~18 / 4 s (23 / 5 s) | ~$0.92 | 36/s → 144 | ~$2.24 | $1.44 |
| Aleph 2.0 | — | — | 28/s → 112 (56 min) | ~$1.75 | $1.12 |
| Veo 3.1 + audio | tens of credits | often >$2 | 40/s → 160 | ~$2.50 | $1.60 |

Same Kling 720p clip: native Kling is cheapest, Higgsfield Plus is close, Runway is about 2×. Same Seedance clip: Higgsfield is the cheaper aggregator. Gen-4.5 keepers are cheaper on Runway than shopping an equivalent flagship on Higgsfield.

## Seedance on OpenRouter (pay per job, 2026-10-11)

From the public catalogue (`GET https://openrouter.ai/api/v1/videos/models`; `promo gen models` prints it live). Billed per video token
(w x h x 24 fps x seconds / 1024); 16:9, no audio. The ledger (`promo gen spend`) keeps each job's estimate next to what OpenRouter billed.

| Model | 4 s at 480p | 4 s at 720p | Lengths |
|---|---|---|---|
| Seedance 1.5 Pro | $0.05 | $0.10 | 4-12 s (1080p $0.23) |
| Seedance 2.0 Mini | $0.13 | $0.30 | 4-15 s |
| Seedance 2.0 Fast | $0.16 | $0.36 | 4-15 s |
| Seedance 2.0 | $0.27 | $0.60 | 4-15 s (1080p $1.50, 4K $3.11) |
| Seedance 2.5 (default) | $0.41 | $0.92 | 4-30 s |

The same Seedance 2.0 clip at 720p is ~$0.60 here against ~$0.92 on Higgsfield Plus and $1.44 on the Runway API; 1.5 Pro at 480p is the cheapest draft of any route.

## Plans (context, not the picker)

Runway monthly: Standard $15 / 625 cr, Pro $35 / 2250, Max $95 / 9500. Annual cards $12 / $28 / $76. Unlimited closed 1 Jun 2026.

Higgsfield (one published set): Starter ~$19 / 270 cr, Plus $59 or $47 annual / 1200 cr, Ultra $129 or $99 annual / 3000 cr. Concurrent video jobs ~2 / 6 / 8. Another published set uses $15 / 200, $49 / 1000, $129 / 3000. Read the live card.

## Speed

Queue time dominates wall-clock more than the model. Higgsfield Plus/Ultra concurrent slots matter for a batch of plates. Higgsfield "unlimited" web windows go to a slow queue; MCP/CLI never get those free slots. Runway Gen-4 Turbo returns faster than Gen-4.5; Aleph and Veo are slow and expensive.
