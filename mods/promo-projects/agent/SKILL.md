---
name: commissionai-mod-promo-projects
description: Show the person their past promo projects in the Stage (the promo-projects mod, /promo-resume), let them search and peek, and pick the one they choose up in this thread.
---
# promo-projects mod: resume a past promo
The person typed `/promo-resume [words]` (or asked to "carry on with / resume / reopen" an earlier promo). They choose; you never pick for them.

**Show the list.** `promo flow projects --out /tmp/promo-projects.json` (add `--query "<their words>"` when they gave any; the Stage pre-fills its search box with it),
then `commissionctl mod publish promo-projects --file /tmp/promo-projects.json`. The list is every flow in the projects dir plus every flow started or
resumed anywhere else on this machine, most recent first; a project whose flow cannot be read shows as such. Do not edit the JSON by hand.
`promo flow projects` without `--out` prints the same list as text (id, name, step, last activity, folder) for you.

**Their clicks arrive as chat messages** starting `[mod:promo-projects]`:
- `picked "<title>" (stopped at <step>) to carry on in this thread`: run the exact `promo flow resume <id>` from the message. It prints the project dir and where it
  stopped. From then on pass `--project <dir>` to every `promo flow` command in this thread. Then:
  1. `promo flow --project <dir> snapshot --out /tmp/promo-flow.json` and `commissionctl mod publish promo-flow --file /tmp/promo-flow.json` (the promo-flow skill takes over from here);
  2. `promo flow projects --resumed <id> --out /tmp/promo-projects.json` and publish promo-projects again, so the picker says which project this thread carries on.
  Then tell them in one or two lines where it stopped and what happens next (the status `promo flow resume` printed). Do not approve or advance anything because it was resumed.
- `cannot see their project in the list. What they said about it: <text>`: look for a folder holding `flow/flow.json` that matches (the projects dir from
  `promo config projects-dir`, the folders they name, recent work folders). Found: `promo flow resume <path>` (this also remembers it), then publish both mods as above.
  Not found: say where you looked and ask where it is with the ask widget. A promo made before the flow existed (a `promo.yaml` without `flow/`) cannot be resumed here; say so.

One thread carries one project: after a resume the picker stops offering Resume (the host rejects it), and the person starts another `/promo-resume` thread for a different project.
