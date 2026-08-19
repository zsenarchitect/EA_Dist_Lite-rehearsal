# Check back — 24h reminder

**Set:** 2026-06-03  
**Check on or after:** 2026-06-04 (~24 hours)

Publisher setup was registered on **EANY-1X8MWP3** (`EnneadTab_SchedulePublisher` every 10 min).  
Ticks only **check**; a **full publish** runs only when new commits are ready.

## Quick status (2 minutes)

1. Open `DarkSide/publish/last_tick_run.txt` or run `_show_last_tick_run.bat`
2. Skim `DarkSide/publish/logs/tick.log` — any errors?
3. Task Scheduler → `EnneadTab_SchedulePublisher` → History: last run succeeded?

## If a full publish ran (see `publish_history.json`)

- [ ] Log ended with `[OK] Publish completed successfully` and post-publish verification OK
- [ ] `../EA_Dist` and `../EA_Dist_Lite` — `git log -1`, remote up to date
- [ ] Wiki log: `revit:` / `rhino:` ingest lines or `local cache hit`; spot-check live wiki
- [ ] `DarkSide/.wiki_ingest_cache.json` updated if wiki ingest ran

## If only skips so far

That is normal until new commits hit `main` and stability rules allow publish.  
Optional smoke test: `.venv\Scripts\python.exe DarkSide\publish\________publish.py` (manual full publish).

## Still open (optional)

- [ ] Delete legacy task **EnneadTab Publisher** (admin) if it still exists
- [ ] Confirm sibling clones exist: `EA_Dist`, `EA_Dist_Lite`, `WIKI_API_KEY` in `DarkSide/.env`

## Phone alert (optional)

1. Install **ntfy** on your phone ([ntfy.sh](https://ntfy.sh) app).
2. Subscribe to a private topic (e.g. `enneadtab-szhang-publish`).
3. Add to `DarkSide/.env`: `NTFY_TOPIC=your-topic-name`
4. Run `_schedule_phone_reminder_24h.bat` — confirms now + pushes again in 24h.

Delete this file after the check is done.
