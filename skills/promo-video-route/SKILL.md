---
name: promo-video-route
description: Pick a video generation provider and model for promo-reel non-UI plates by speed and price (Higgsfield vs Runway, Kling vs Gen-4 Turbo vs Gen-4.5 vs Cinema Studio vs Aleph vs Seedance). Use when generating b-roll, backgrounds, transitions or scenery clips, when asked which video model to use, or when routing a job through a Higgsfield or Runway ACP-agent connector. Use when the user runs /promo-video-route.
---

# promo-video-route

promo-reel specifies and ingests plates (`promo gen plan` / `promo gen register`). You generate them. This skill picks **where** and **which model**. Team rules and ingest live in `skills/promo-reel/SKILL.md` and AGENTS.md rule 1 (generated non-UI plates only).

## Reach the vendor through this agent's connectors

promo-reel never calls Runway or Higgsfield. CommissionAI does not inject those MCP servers. Use the connector already on **this** ACP agent.

1. If this session already has Higgsfield or Runway generation tools, use them.
2. Else if `higgsfield` is on PATH, use the Higgsfield CLI.
3. Else ask the person to connect on this agent (they sign in; you do not paste keys), then continue.

| Agent | Higgsfield | Runway (generate media) |
|---|---|---|
| Claude Desktop / claude.ai | Settings → Connectors → `https://mcp.higgsfield.ai/mcp` | Settings → Connectors → `https://mcp.runwayml.com/mcp` |
| Cursor | Marketplace → Higgsfield | MCP URL `https://mcp.runwayml.com/mcp` |
| Claude Code, Codex, OpenClaw, Hermes | CLI: `npm i -g @higgsfield/cli`, `higgsfield auth login`, `npx skills add higgsfield-ai/skills` | Person adds `https://mcp.runwayml.com/mcp` on that agent (ACP sessions often see the CLI more reliably than injected MCP) |
| Grok | Higgsfield plugin if the harness lists it | Runway MCP if the harness lists it |

Use `https://mcp.runwayml.com/mcp` for generation. `https://dev.runwayml.com/mcp` is Runway Dev (building apps). `https://mcp.runway.team` is a different product.

Higgsfield MCP/CLI always burns credits. "Unlimited" windows exist only on higgsfield.ai in the browser.

If neither connector is available, fall back to `promo gen detect` and the grok / codex CLIs in the promo-reel skill.

## Pick the model

Read `promo gen plan --json` first. Use its guard-prefixed prompt. Target: 4 s, 16:9, ≥720p (register upscales to 1080p).

Name the model in the tool call. Do not let the connector auto-pick a flagship (Veo, Seedance Pro, Aleph) for a texture plate.

| Job | Provider | Model | Why |
|---|---|---|---|
| Cheap/fast draft plate (sky, bokeh, light leak, macro, flow sample) | Higgsfield | Kling 3.0 at 720p | cheapest quality-ok clip on the aggregator |
| Even cheaper draft if Kling is overkill | Higgsfield | Wan 2.7 / Wan 3 at 720p | fewer credits than Kling |
| Many plates in parallel | Higgsfield Plus/Ultra | Kling 3.0 at 720p | 6–8 concurrent video jobs |
| Fast draft on a Runway-only agent | Runway | Gen-4 Turbo | 5 credits/s |
| Keeper scenery for the cut | Runway | Gen-4.5 | native quality; 12 credits/s |
| Camera-move cinematic plate | Higgsfield | Cinema Studio | camera language |
| Same character/face across plates | Higgsfield | Soul ID + Kling or Cinema Studio | Soul lives on Higgsfield |
| Edit, restyle, or extend an existing clip | Runway | Aleph 2.0 | 28 credits/s; only when editing |
| Kling specifically | Higgsfield | Kling 3.0 | same model is dearer on Runway credits |
| Seedance | Higgsfield | Seedance 2.0 / 2.0 Fast | Runway Seedance is several times the credits |

Default for promo-reel: **drafts on Higgsfield Kling 720p; keepers on Runway Gen-4.5**. Skip Veo and Aleph unless the brief names them.

Before a paid batch, check credit balance, say model + credits + ~USD, then generate. Prefer the connector's live credit quote over the dated table. Flow *samples* (labelled SAMPLE, never in the footage manifest) stay on the cheap draft row.

Storyboard frames are images: use the session's image tool or `promo gen image`. Do not spend video credits on a still.

## After the file exists

```
promo gen register FILE -p projects/<n>/promo.yaml --id <id> --prompt "..." --provider higgsfield:kling-3.0 --shots <ids>
```

`--provider` is who made it, with the model in the string (`higgsfield:kling-3.0`, `runway:gen4.5`). Then `source: <id>` on a `ui: false` shot.

Dollar and credit tables: [references/prices.md](references/prices.md). Re-check vendor pages before a paid batch; plans move.
