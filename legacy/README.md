# Legacy

Earlier material, kept for reference only. Nothing here is served by `kasflex ui`,
packaged in the apps, linted or tested, and it may not match the current code.

| Path | What it was |
|---|---|
| `grower-screen/` | The first grower screen, served at `/legacy-grower` until October 2026. Replaced by the grower workspace at `/` (`src/kasflex/ui/static/demo.*`). |
| `notes/DESIGN_NOTES.md` | Early design notes for the interface. |
| `notes/MVP_NEXT.md` | An early add, change and remove list. The current status is in [docs/research/MVP_PLAN.md](../docs/research/MVP_PLAN.md). |

To look at the old screen, copy `grower-screen/*` into `src/kasflex/ui/static/` and
add `"/legacy-grower": "grower.html"` back to `_PAGES` in `src/kasflex/ui/http.py`.
It is no longer maintained or checked for security and accessibility, so do not use
it with participants.
