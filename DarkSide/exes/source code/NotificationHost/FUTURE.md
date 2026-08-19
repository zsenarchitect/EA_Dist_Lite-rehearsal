# NotificationHost — future work (post-v1)

v1 is good to ship: persistent host, inbox IPC, stacked bottom-left cards,
hover chrome, images/GIF, YouTube thumbnail + Open, mute, Messenger fallback.

Do **not** block distribution on the items below.

## v2+ backlog

1. **YouTube in-card play (optional)** — Qt WebEngine embed, click-to-play;
   heavier exe; keep thumbnail+Open as default path.
2. **Async media fetch** — YouTube thumb download off the UI thread so enqueue
   never stalls the host loop. *(Partial: network fetch moved off UI in host
   enqueue; keep improving progressive image attach after card is already shown.)*
3. **Cold-start / dual process** — PyInstaller onefile normally shows **two**
   `NotificationHost.exe` rows (bootloader ~9MB + app ~60MB). Real duplicate
   wake races are separate; prefer mutex+alive checks over process count.
4. **Phase B — fallback telemetry** — log Messenger fallback hits
   (host missing / crash) so we know when legacy is idle in the wild.
   ⚠️ **Must be TIER-SPLIT (full EA_Dist vs lite).** A blended rate is
   meaningless — see the block below.
5. **Phase C — remove fallback** — ~~drop `_legacy_messenger_fallback` from
   `NOTIFICATION.messenger` after fallback rate is near-zero.~~
   🚫 **BLOCKED — see below (senzhang-todo #3910).**
6. **Phase D — delete Messenger** — ~~remove `Messenger.py` / `.exe` /
   `.sexyDuck` and dead `window_msg` path.~~ 🚫 **BLOCKED — see below.**
7. **Phase E — duck_pop (optional)** — playful NotificationHost skin, or keep
   DuckPop as a separate fun path.
8. **Dist publish** — ✅ **DONE for the full tier, and it always was.**
   `lite_allowed_exes` is consulted only under `if is_lite_version`
   (`________publish.py:3317-3342`); the full dist copies every exe wholesale,
   so `NotificationHost.exe` already reaches full EA_Dist. **Deliberately NOT
   added to lite** (2026-08-12): it is 37.9 MB against a 68 MB total lite exe
   payload whose largest member is 10.6 MB, which defeats lite's stated
   size-reduction purpose.

### 🚫 Why Phases C and D cannot execute (2026-08-12)

Decision: **notification ability stays in lite; the progress bar skips lite.**
Lite ships `Messenger.exe` and never `NotificationHost.exe`, so on every lite
machine `locate_executable` finds no host, `ensure_notification_host()` returns
False, and `_legacy_messenger_fallback` fires **100% of the time by design**.
Messenger is lite's *only* notification renderer.

Consequences:
- Phase C's exit criterion ("fallback rate near-zero") can never be met
  fleet-wide. It is pinned at 100% on the lite tier permanently.
- Phase D would delete notifications from the lite tier outright.

**The trap Phase B would have walked into.** Before the 2026-08-12 fix
(`35fa90331`), `ensure_notification_host()` returned True as soon as
`os.startfile` did not raise — on *every* machine, including ones where nothing
started. Phase B counts fallback **hits**, so it would have measured a rate near
**zero** and read that as "legacy is idle, safe to remove" — greenlighting
Phase C at exactly the moment the fallback was the only thing still capable of
delivering a message to a user. **Any fallback-rate figure collected before
2026-08-12 is meaningless; do not use it.**

To unblock: rescope C/D to full-EA_Dist-only (keeping Messenger for lite), or
give lite a lightweight renderer that is not the 37.9 MB host.

## v1 API reminder

```python
NOTIFICATION.messenger(
    "text",
    level="info",           # info|success|warning|error
    image=r"C:\path.png",   # or gif; or a YouTube URL
    youtube="https://youtu.be/...",
    actions=[{"id": "x", "label": "Open", "type": "open_url", "payload": "..."}],
    animation_stay_duration=8,
)
```
