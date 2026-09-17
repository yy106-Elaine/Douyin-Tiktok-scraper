# Collection plan

Three platforms, once a day each, for two weeks. Target: everything posted in
the last 24 hours that matches a keyword list.

## What differs by platform

This is the most important table in this document. The three platforms are not
one method applied three times, and an analysis that treats them as one will be
wrong.

| | YouTube | TikTok | Douyin |
|---|---|---|---|
| How it is read | Data API | phone screen | phone screen |
| Manual effort | none | ~30 min/day | ~30 min/day |
| Video ID | always | only if a link was copied | only if a link was copied |
| Publication time | exact, from the API | exact, decoded from the ID | exact, decoded from the ID (unverified) |
| Engagement counts | exact integers | abbreviated, approximate | abbreviated, approximate |
| Author identity | channel ID, always | `@handle` only after resolving a link | same |
| Re-check method | ID lookup | page wording | page wording |
| Re-check reliability | high | marker list, not yet verified | marker list, not yet verified |
| Status | working | working | **not started — app not installed** |

The practical consequence: **YouTube coverage will be near-complete and
TikTok/Douyin coverage will be a fraction of what was seen.** Only videos whose
link was copied have an ID, and only videos with an ID can be re-checked at
all. Report that fraction per platform; the overview page shows it as "With ID".

Do not pool the three platforms into one takedown rate without saying that the
YouTube subset is a census of its keyword results while the other two are a
convenience sample of what one person had time to copy.

## Daily routine

### Morning, on the phone (~60 min total)

For TikTok, then Douyin:

1. Search a keyword from the list.
2. Filter to the last day where the app offers it.
3. For every result: **share → copy link → tap the blue floating button**.
4. Move to the next keyword.

A video with no copied link is metadata only. It cannot be re-checked, so it
cannot be part of a takedown finding.

### Then, on the Mac (~5 min, mostly waiting)

```
cd ~/Douyin-Tiktok-scraper/backend

# 1. YouTube: search and store. No scrolling needed.
./.venv/bin/python -m app.youtube collect --keywords keywords.txt --hours 24

# 2. Turn the copied short links into video IDs and @handles.
./.venv/bin/python -m app.resolve

# 3. Re-check everything due, on every platform.
./.venv/bin/python -m app.recheck

# 4. Keep yesterday's database. Takes a second; there is no other copy.
mkdir -p backups && cp scraper.db "backups/scraper-$(date +%F).db"
```

Then open the overview and check the numbers moved:
`http://localhost:8000/dashboard/overview?key=...`

### Keywords

One per line in `backend/keywords.txt`; lines starting with `#` are ignored.
The same file drives YouTube. TikTok and Douyin are searched by hand from the
same list, so the three platforms stay comparable.

## Quota and rate limits

YouTube's default is 10,000 units a day. A search costs 100 units, a details or
re-check call costs 1. So roughly 90 keyword-searches a day, and re-checking is
effectively free (50 IDs per call). Every run prints what it spent.

TikTok and Douyin have no API here; `resolve` and `recheck` pause 1–2 seconds
between requests. Getting blocked mid-collection loses observations that cannot
be recovered, because the videos may be gone before access returns.

## Cadence, and what it costs in precision

Re-checks thin out as a video ages: at least 8 hours apart for the first 48
hours, then 20 hours, then 6 days, then 27. Removals cluster early, so this
spends requests where they measure something.

The gap between two consecutive checks **is** the precision of every
disappearance time. A video alive on one check and gone on the next went
somewhere in between. Findings therefore carry `last_alive_at`, `first_gone_at`
and the width between them, and a lifetime is quoted as a bracket. Missing a
day widens that bracket for everything checked that day — which is recorded,
because actual check times are stored, not scheduled ones.

## Two weeks in

Expect, per platform: number collected, number with an ID, number re-checked,
number disappeared, and the median removal window. The overview page is that
table.

Before quoting any rate, confirm the TikTok and Douyin marker lists against one
genuinely removed video each. Until then their disappearances read as
`unknown`, which is safe — it never reads as `alive` — but it is not yet a
measurement. YouTube needs no such check: a missing ID is a missing video.

## What this design cannot see

- **Regional blocking.** All checks run from one machine in one country. A
  video blocked elsewhere and visible here is indistinguishable from an
  available one.
- **Who removed it.** An author deleting a post and a platform pulling it can
  return the same page. `gone` means unwatchable, not moderated. Separating
  those is what the author interviews are for.
- **What was never rendered.** The phone platforms only ever see what the app
  drew on screen for one person scrolling.

Full detail: `docs/METHODOLOGY.md`.
