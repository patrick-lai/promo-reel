# Recipes

One technique per file, used by `promo flow recipe`. The round brief offers up to three that fit what is still open; a council or the agent
marks the ones it applies (`promo flow recipe use ID`, which adds the recipe's `check`), and the round's outcome is credited to them
(`promo/lessons.py`): a win when that check passes on the draft the round closes with, a loss when it fails there or a blind judge preferred
the earlier draft. Two wins, more wins than losses:
promoted. Three losses, at least twice the wins: retired, never offered again. Stats live beside the promo-reel config, not here.

    id:       lower-case words joined by - or .  (hook.result-first)
    kind:     hook | pacing | caption | camera | sound | grade | end-card | story
    styles:   [hero, anime-opening, livestream, cinematic-story, horizon] or [any]
    intent:   what it is for, in one sentence
    how:      how to do it with promo-reel (keys, commands)
    check:    what a reviewer can see on the draft when it worked (becomes a check when used)
    evidence: where it comes from (a reference study, a team rule, a URL)

A project's own recipes go in `<project>/flow/recipes/*.yaml` (`promo flow recipe add --file F`); they are offered only in that project.
Every claim a recipe makes on screen still follows AGENTS.md rule 3: it shows the real product, it never invents a number.
