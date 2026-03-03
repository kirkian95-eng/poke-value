# /status — Show roadmap progress

Read `tasks.yaml` and print a progress report.

## Output format:

```
ROADMAP STATUS
==============

Phase 1 — Foundation + Quick Wins
  [done] chartjs-setup (2/2 subtasks)
  [>>>]  nav-overhaul (1/2 subtasks — working on: nav-dashboard)
  [ ]    set-completion-cost (0/5 subtasks)
  ...

Phase 2 — Analysis Tools
  [ ]    cross-set-rarity (0/3 subtasks)
  ...

Overall: X/50 subtasks done | Y/16 features done

Next up: <feature name> — <subtask name>
  <subtask description, first 100 chars>
```

Use these symbols:
- `[done]` = all subtasks complete
- `[>>>]` = has at least one in_progress subtask
- `[ ]` = pending (no subtasks started)

Group features by the build order phases defined at the bottom of tasks.yaml.
