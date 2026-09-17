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

### 9. YouTube is a different instrument, and must be reported as one

YouTube is read through its Data API, not off a screen. That removes most of
this document's limitations for that platform and it would be misleading to
present the three as one method:

| | YouTube | Douyin / TikTok |
|---|---|---|
| Video id | always present | only when a link was copied |
| Publication time | the API's own `publishedAt` | decoded from the id (§2b) |
| Counts | exact integers | abbreviated, approximate (§1) |
| Author identity | channel id always | `@handle` only after resolving |
| Re-check | id lookup; a missing id is a missing video | page wording (§8) |
| Sampling | every result the API returns for the keyword and window | whatever one person had time to copy |

`counts_approximate` is false for YouTube rows and the publication source is
labelled `api` rather than `screen`, so the difference is visible per row
rather than something a reader has to remember.

The sampling difference is the one that matters most. The YouTube subset is
close to a census of its keyword results; the phone subsets are convenience
samples of what was copied during a collection session. **Do not pool them into
a single takedown rate without saying so.**

`relevanceLanguage` and `regionCode` are part of the sampling method, not
preferences: they change which results the API returns. They are configured in
`.env` (default `YOUTUBE_RELEVANCE_LANGUAGE=zh-Hans`, no region) and **stored
on every row**, so changing one halfway through a study is visible in the data
rather than something to remember. Report the values used, and treat a change
as a change of sample.

Ordering is `date`, never relevance: the study samples a time window, and
relevance ranking would silently decide which videos in that window got in.

The collection window is **72 hours, run daily**, so each run re-covers the two
days before it. This is a coverage decision, not a convenience: YouTube's
search index lags publication, so a video posted an hour ago is often not yet
searchable, and a strict 24-hour window would miss the newest videos
systematically rather than at random — the exact population under study. The
overlap costs nothing, because a video already stored is skipped without a
details call, so the corpus holds one row per video and "collected" counts
videos rather than runs. State the window and the run frequency together; one
without the other does not describe the sample.

One limitation YouTube does *not* escape: which party removed a video is still
absent from the response, and the id lookup cannot separate a deletion from a
regional block either.

### 10. What a keyword search returns is not what the study is about

The study is of Chinese-language WLW content, so `app/relevance.py` requires
exactly that: the text must be **in Chinese** and carry a term placing it **on
topic**. Anything else is out of scope by definition.

That is the right way round. Filtering out noise as it is noticed leaves the
corpus defined by whichever collisions someone happened to catch; requiring
inclusion puts the burden on the text to qualify. In Chinese the difference is
large, because the search terms are substrings of ordinary words:

| term | collides with |
| --- | --- |
| 女同 | 女同学, 女同事, 女同桌, 女同胞 — school and work |
| 拉拉 | 拉拉裤 (adult nappies), 货拉拉 (delivery), 巴拉拉小魔仙 (a children's show), 拉拉队 (cheer squad) |
| 百合 | the lily, and a cooking ingredient (西芹百合炒虾仁) |
| 同性恋 / 同志 | gay men equally; and 同志 means "comrade" or "client" in divination lessons |

`女同性恋` is unambiguous; every other term needs a qualification, and two
kinds were necessary:

- **Adjacent-character boundaries** for 拉拉 and 女同. This is where the first
  version was wrong: listed bare as a topic term, 拉拉 matched inside 拉拉裤
  and then *overrode* the exclusion written to catch it, so every packet of
  nappies stayed in the corpus. A term cannot be both the signal and the
  collision without boundaries.
- **Context** for 百合 and for 同性恋/同志, where no adjacent character helps.
  百合 counts unless cooking or horticulture words appear beside it; 同性恋 and
  同志 count only beside a female marker.

Exclusion reasons, all of which hide the row:

| reason | what it catches |
| --- | --- |
| `advertising` | escort bait: a booking phrase plus a Telegram or WeChat contact |
| `ai generated` | synthetic, so no author an interview could follow up |
| `divination` | 紫微斗数, 八字, 塔罗, 风水 — a genre where 女同志 means "female client". Hard rather than soft, because the case that prompted it carried a topic term and still had to go |
| `unrelated product` | 拉拉 inside a brand or product name |
| `not about the topic` | 女同 inside a word about a classmate or colleague |
| `gossip` | 八卦, 吃瓜 — soft, since gossip about a lesbian public figure carries a term of its own |
| `not wlw` | male-only content reaching in through a shared term |
| `not in chinese` | the study is of Chinese-language content |
| `no topic term` | nothing placed it on topic |
| `no text` | the parser read no caption |

**Rows are marked, never dropped.** A video a filter deletes is a video whose
disappearance can never be observed, and nothing in the data would show it had
been there — the one failure a takedown study cannot detect after the fact.
`?show=all` lists the excluded rows with their reasons, so the filter is
audited rather than trusted.

**One carve-out**, in `app/views.py`: a Douyin or TikTok row whose link was
copied by hand is never hidden. Those were chosen one at a time by a person,
and their captions are frequently truncated to `...more` or absent, so the text
is no evidence about the video. They are also the rows that cost the most to
collect. YouTube gets no such exemption — the API chose those results, not a
person.

**Recall is the risk this design takes on.** A term missing from the topic list
excludes real videos. It is survivable because the verbatim payload is kept for
every observation: `python -m app.relevance` re-marks the whole corpus from it,
so a corrected rule reaches rows collected weeks earlier and nothing has to be
collected again. Check a rule against text without touching the database:

```
./.venv/bin/python -m app.relevance --test "百合短剧 治愈女同"
./.venv/bin/python -m app.relevance --test-file captions.txt
```

Report the rule set used and the counts per reason; running `app.relevance`
with no arguments prints both, `--by-keyword` attributes them to the search term
that produced them, and `--by-param` groups them by the sampling parameters in
force.

The first 150 YouTube results were 71% `not in chinese`, and the per-keyword
breakdown found the opposite of what was expected:

| keyword | found | in scope | note |
| --- | --- | --- | --- |
| 拉拉 | 30 | 17 (57%) | best yield; its noise is 拉拉裤 / 货拉拉, which the filter catches |
| 女同 | 12 | 4 (33%) | |
| 女同志 | 9 | 2 (22%) | |
| 女同性恋 | 110 | 3 (3%) | 105 of them not in Chinese |

**The most precise Chinese term leaks into other languages the most.** 女同性恋
is a clean translation of "lesbian", so the search maps it across languages and
returns English and Spanish results; 拉拉 and 女同 are community slang with no
such mapping, and stay Chinese. This belongs in a methods section, because the
intuition — that the formal term is the safer one — is wrong here: a study that
pruned to the formal term alone would have collected almost no Chinese
community content while believing it had the cleanest possible sample.

None of this argues for dropping a keyword. Off-topic rows are marked rather
than deleted, and quota is not the binding constraint at this volume: three
keywords over a 72-hour window cost 704 of 10,000 daily units. Precision is
cheap, while a keyword dropped is recall that cannot be recovered afterwards —
the videos will be gone. 女同 was dropped on the assumption its collisions
would dominate, and restored when the data showed they cost 2 of its 12
results.

**`relevanceLanguage` does little, and that is measured rather than assumed.**
Every row of the first 340 was collected with `zh-Hans` in force, and 67% of
them still have no Chinese in the title or description. There is no control
group in this data — the hint was configured before the first successful run,
so the before/after comparison the per-row parameters were meant to support
does not exist. What the number does establish is the reportable part: with the
hint set, two thirds of results are in another language. It is a ranking hint
the API may ignore, not a language filter, and a methods section should not
imply the sample was language-restricted at source. The Chinese-language
requirement is enforced here, after collection. Two judgement calls worth stating explicitly,
because they are defensible either way: general `同性恋` news with no female
marker is excluded, and non-Chinese posts are excluded even when they carry an
English WLW hashtag.

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
