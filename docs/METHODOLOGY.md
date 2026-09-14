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

### 2. Most posts have no video id

The accessibility tree contains no video id, so `video_id` and `video_url` are
populated **only** for posts the participant also shared into the app. Plan
for two tiers:

- **all captured posts** — metadata, no citable URL;
- **the shared subset** — metadata plus a verifiable link.

Anything requiring a link (manual coding, retrieval of the video, checking
whether it was later deleted) can only use the second tier. Say what fraction
that was.

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
error**. Mitigations:

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

## Ethics and consent

- Collection is limited at the OS level to the two target apps
  (`android:packageNames`), so no other app is observable.
- Comment **text** is never collected — only counts.
- Registration is gated on an approved-participant whitelist.
- Participants can see what is pending and stop the service at any time via
  Android's accessibility settings.
- Device identifiers are random per-install UUIDs.

Accessibility services are a powerful permission. The consent form should say
plainly what is read, from which apps, and how to switch it off.
