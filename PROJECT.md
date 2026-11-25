# Morning Brief
Hub slug: morning-brief
Board: personal

## Goal
A free morning briefing: market numbers and news, summarized each morning, published to a phone-friendly page with a push notification.

## Milestones
- [x] Sessions report to Wingman (rule in CLAUDE.md)
- [x] PROJECT.md added so the hub can track this project
- [x] Daily pipeline live: markets, breadth, watchlist, news, policy, mortgage, lessons, audio
- [x] 2026-11-25 fixes: PMMS quoted-CSV parse plus last-good mortgage fallback, one Gemini backoff retry with the error class in data_availability, FHFA 2027 loan limit shown as announced, 414A date rules (dates field, prompt rule, invented-date check), Utah sortable-header fix, US contest-vocabulary guard
- [ ] Data Smoke fully green on the next scheduled Monday run (Nov 30); 13's C4 stays red until the Nov 20 edition leaves its 7-day window on Nov 28

## Next step
Check the Nov 30 Data Smoke run. If 07 A6 is still red, the Utah rows changed shape too, not just the header.

## How to keep this current
After meaningful work, tick or add milestones and update Next step. Keep each line short and plain. No em dashes.
