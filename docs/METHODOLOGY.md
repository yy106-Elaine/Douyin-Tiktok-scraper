# Methodology notes

Written for the methods section of a thesis. Every limitation here is a
property of screen-reading collection, not a bug to be fixed later.

## What this instrument measures

**Exposure, not content.** A row means "this post was on this participant's
screen on this date". It is evidence about what the recommender served, which
is the thing a feed study usually wants.

## Known limitations, and what to say about each

### 1. Engagement counts are approximate

Both apps abbreviate: TikTok renders `74.9K`, Douyin renders `12.3万`. The
underlying value is unrecoverable — a displayed `12.3万` is anything from
123,000 to 123,999, an error of up to ±0.4%.

Every structured row carries `counts_approximate`. Report it:

> Engagement counts were read from the rendered interface and are therefore
> abbreviated at magnitude (e.g. "12.3万"). Values above 10,000 (Douyin) or
> 1,000 (TikTok) carry rounding error of up to 0.5%. N = _ rows were flagged
> approximate.

Do not report these counts to more significant figures than the display had.
Prefer bucketed or log-scale analysis over exact arithmetic.

### 2. Video ids are not guaranteed

Three paths can supply one, in descending order of preference:

1. **Read off the screen.** Each frame is scanned for an id-shaped token
   (18-19 digits). This costs no interaction with the app, so it sends no
   engagement signal and cannot influence what the recommender serves next —
   which matters in a study of the feed itself. The app's self-check reports
   how many frames carried one, so whether this works is a measurement rather
   than an assumption.
2. **Shared by hand.** The participant shares a video into the app, or pastes
   a copied link. Exact when the device knew which post it was harvesting for.
3. **Nothing.** Metadata only, no citable URL.

Do not drive the platform's own share sheet automatically to obtain ids.
Opening a share sheet and copying a link are engagement actions; performing
them on every post would systematically alter the feed under study, which is
an endogeneity problem no amount of coverage compensates for.

Where ids are missing, plan for two tiers:

- **all captured posts** — metadata, no citable URL;
- **the shared subset** — metadata plus a verifiable link.

Anything requiring a link (manual coding, retrieval of the video, checking
whether it was later deleted) can only use the second tier. Say what fraction
that was.

### 2b. Publication time is recovered from the id, not from the screen

Both platforms mint video ids Snowflake-style: the high 32 bits of the 64-bit
id are the creation time in whole seconds since the Unix epoch. So once an id
is known, so is the publication time — to the second, with no request to the
platform and no dependence on what the interface happened to render.

This matters because the rendered value is poor for this purpose. The feed
shows publication as `11h ago`, or as a partial date with no year, or omits it
entirely. A time-to-removal computed from `11h ago` inherits that rounding;
one computed from the id does not.

The value is therefore **derived, not stored**. `video_id` is the recorded
fact; `posted_at_exact` and `posted_at_source` are a pure function of it,
computed on read by `app/snowflake.py` and present in the CSV export. There is
no second copy to fall out of date.

Report which source each observation used — the dashboard labels every row,
and the export carries `posted_at_source`:

| `posted_at_source` | meaning | precision |
| --- | --- | --- |
| `video id` | decoded from the id | to the second |
| `screen` | parsed from the rendered string, resolved against capture time | whatever the UI rounded to |
| `as shown` | the rendered string, unparsed (e.g. a partial date) | not a timestamp |

**Two caveats belong in a write-up.**

The derivation is confirmed for TikTok and reproducible against any post whose
date is independently known. Douyin runs on the same infrastructure and the
same arithmetic yields plausible times, but no Douyin post has been checked
here against a known publication date, so the dashboard marks a Douyin
derivation `from id?` and `app.snowflake.derivation_is_verified` returns false
for it. Verify it once — capture a post whose date the interface shows in full,
then compare — and move `douyin` into the verified set.

Second, an id decoding outside 2016–now is refused rather than returned. A
wrong date silently becomes a data point; a missing one does not.

### 3. Pairing is heuristic

A shared link is matched to a captured post by participant, platform, author
handle, and a ±15 minute window (`PAIRING_WINDOW_SECONDS`). It refuses to
match when the author handles disagree, so false positives need two videos by
the same author within the window. False negatives are more common: sharing
long after viewing leaves the link unpaired.

`shared_links.matched_capture_id` is null for every unpaired link — count
them, and report the pairing rate.

### 4. Post identity can collide

Without a video id, a post is identified by
`platform::author::first 20 characters of caption`. One author posting two
videos whose captions share a 20-character prefix — common with templated
captions and series content — collapses into one row. Posts with a paired
video id are exact; the rest carry this risk.

### 5. Parsers are version-specific and fail silently

Selectors are written against the view ids and UI strings of one build of one
app. An update can change them, and the failure mode is **empty fields, not an
error**.

The two parsers do not carry equal confidence. TikTok's selectors are
cross-checked against a collector known to work; **Douyin's are unverified
hypotheses** and should be assumed wrong until a device says otherwise. Do not
report Douyin coverage figures from an uncalibrated run.

Mitigations:

- re-verify selectors before and after each collection wave (`SELECTORS.md`);
- monitor the null rate per field per day — a step change means a broken
  selector, not a change in user behaviour;
- pin the app version on study devices and disable auto-update if the IRB
  protocol allows it.

### 6. Comment sheets are skipped, not parsed

When the comment sheet is open the frame is discarded, because a long comment
is easily mistaken for a caption. So a post the participant engaged with
deeply may have *fewer* observations than one they scrolled past. Do not treat
observation count as an engagement proxy.

### 7. Coverage is bounded by what is rendered

Posts scrolled past faster than the 500ms sampling interval may be missed
entirely. This under-counts rapid scrolling. It is a floor on exposure, not a
census.

### 8. The takedown check measures unwatchability, not moderation

`app/recheck.py` revisits every collected link and records what the server
returned. `app/survival.py` turns that history into a finding. Five things
about it belong in a write-up.

**A removed video does not answer 404.** Both platforms commonly serve HTTP 200
with a page saying the video is unavailable, so "did the request succeed" would
report every video as alive. Classification reads the page's wording; the
status code is one input among several.

**The verdict is not stored.** `link_checks` keeps the status, the final URL,
the page title, a bounded excerpt and which marker phrases matched. Verdicts
are computed on read. This is deliberate: the marker list is the part most
likely to be wrong, and a stored boolean could not be corrected for videos
that are already gone. A corrected list re-reads the whole history.

**The marker list is checkable, not verified.** It comes from the platforms'
published wording, not from a removed video observed here. Two safeguards: a
page matching nothing is `unknown`, never `alive`, so a stale list appears as a
growing unknown count rather than a quietly wrong survival curve; and the
stored excerpt makes re-classification possible. **Confirm the wording against
one genuinely removed video before quoting a rate.**

**No information is never counted as an outcome.** Timeouts, rate limits, bot
challenges and unrecognised pages are excluded from the denominator, not
assumed alive. `Summary.rate` returns `None` rather than 0% when nothing was
measured — 0% is a claim. Report the excluded count alongside any rate.

**Removal time is an interval.** A video seen alive on one check and gone on
the next disappeared somewhere between them. Every finding therefore carries
`last_alive_at`, `first_gone_at` and the width between them, and a lifetime is
a bracket (`56d 14h–58d 14h`), never a point. Quoting the later timestamp
would present the checking schedule as a property of the platform. Because
checks are manual, the actual check time is recorded, never the due time.

**What it cannot distinguish.** The five disappearance types the study cares
about do not all separate from one response:

| type | distinguishable? |
| --- | --- |
| platform removal | not from author deletion — the page is often identical |
| author deletion | not from platform removal |
| account ban or deletion | yes — the author page is checked whenever a video is missing, and `author gone` outranks the video's own wording |
| set to private | usually — distinct wording, recorded as `withheld`, not `gone` |
| regional restriction | **no.** Checks run from one location. A video blocked elsewhere and visible here is indistinguishable from an available one. Not measured; state this as a limitation. |

So `gone` means *unwatchable from here*, not *moderated*. Separating the first
two types is what the author interviews are for; this instrument tells you
which videos to ask about and brackets when it happened.

**Coverage.** Only videos with an id can be re-checked, so the findings table
is a subset of what was observed. Report that fraction — the capture dashboard
shows it as "With a video ID".

## Ethics and consent

- Collection is limited two ways: the OS delivers events only for the two
  target apps (`android:packageNames`), and each frame is checked to belong to
  one of them before it is read. The second check exists because the first is
  not enough — an event from the feed can arrive while the task switcher is the
  active window, and an early session captured exactly that. State both limits
  rather than only the first.
- Comment **text** is never collected — only counts.
- Registration is gated on an approved-participant whitelist.
- Participants can see what is pending and stop the service at any time via
  Android's accessibility settings.
- Device identifiers are random per-install UUIDs.

Accessibility services are a powerful permission. The consent form should say
plainly what is read, from which apps, and how to switch it off.
