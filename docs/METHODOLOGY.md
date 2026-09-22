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

**One post, two rows.** A post's identity on the device is its author plus
the head of its caption, so a read taken before the caption renders has a
different identity from the read taken after, and both are stored. The
assisted loop guarantees the gap: the share sheet covers the feed for several
seconds between the two reads, long enough for the first to settle.

The blank row holds nothing the other does not, and left alone it inflates the
row count and halves every caption-coverage figure. `python -m app.dedupe`
reports the pairs and `--apply` folds them, matching a blank row to a captioned
one by author, day and like count -- the number that is on screen before the
caption is. Anything ambiguous is left alone: two rows merged in error lose a
video, which is worse than a duplicate. Only the derived row is deleted; the
`capture_events` payload it came from stays, so the observation as the device
reported it is still on file.

**Times are stored in UTC and read in Eastern.** Every column holds UTC,
because an instant is an instant and a database that mixes zones cannot be
compared with itself. Everything shown converts, and so does every day
boundary: a collection run at 22:52 in Boston is 02:52 the next day in UTC,
and the per-day chart was filing that evening's work under tomorrow while the
day it happened on read zero. `app/clock.py` is the only place that converts,
and `display_timezone` in the settings is the zone — set it to wherever the
study is actually run from.

**The corpus is two populations, and they are never pooled.** A keyword search
returns both a person posting their own life and an AI-produced 百合短剧
channel posting episode after episode. Both are Chinese-language WLW content
and both can be taken down, so both are in the corpus and both are tracked.
They are not one population: a channel on a production schedule has no author
to interview about a removal and answers to different incentives, so a single
rate over the two describes neither.

`app.relevance` labels scripted drama `fiction`. The dashboard lists the two
strata separately (`show=firsthand`, `show=fiction only`) and reports a
takedown rate for each rather than one pooled figure; the export carries the
label, so any analysis can make the same split. The boundary is a regular
expression over the title and description and will misplace rows near it —
read both lists before quoting either rate.

**A collection window has to be the same every day, or the daily counts are
about the windows.** `app.youtube collect --hours N` looks back N hours, so a
24-hour run and a 48-hour run return different amounts of the same world. Runs
made at 24, then 48, then 12 hours produced a per-day series that fell from 22
to 17 to 15 to 7 — which reads as the community posting less and is mostly an
artifact of how far back each run reached. The daily job fixes the window
(`WINDOW_HOURS`, 72 by default, overlapping on purpose so nothing is missed
when a run is skipped) and is the only collector whose output belongs in a
trend. An ad-hoc run with a different `--hours` is worth making — it finds
videos — but the day it lands on is no longer comparable to the others, and a
figure drawn across both is not a measurement.

**What is tracked is the corpus, not the search.** A YouTube search for the
keywords returns mostly other things: of 1,126 videos collected over three
days, 1,072 were excluded — 504 not in Chinese, 256 Japanese, 200 with no
topic term, and the rest products, fiction, games and divination. That ratio
is itself a finding worth reporting: the community's practice on YouTube is
thin compared with Douyin and TikTok, and the search reaches it only through a
great deal of noise.

The excluded rows are counted, written to a CSV and then removed from the
database by `python -m app.prune` (`--apply` writes; the CSV is the audit
trail, because the classifier is fallible -- 拉拉裤 and 巴拉拉小魔仙 both had
to be taught -- and "read a category before trusting it" stops being possible
once the rows are gone). Removing a row takes its `capture_events` payload and
any re-checks made against its id with it. Platforms with no topic filter are
never pruned. Until a corpus is pruned its excluded rows are still not
re-checked. Every one
of them was, at first, and a takedown rate computed over adult nappies and
Japanese vlogs was being presented as the corpus's. `collected_targets` now
applies the same scope condition the dashboard and the export use, so
re-marking a row moves it in or out of tracking at the next run; the checks
already made stay on file, and the findings are recomputed from them.

A copied link that never paired to a post has no relevance to read, and is
tracked. On Douyin and TikTok the search is the filter, and a hand-copied link
is a video someone chose.

**One post, many copies.** When a day's search results run out the feed stops
advancing and the loop keeps copying whatever is on screen; one run copied a
single post eighty times. Every copy is a real observation and stays in
`shared_links`. The dashboard shows the post once, marked with how many times
it was seen, folding rows that share an author and the first ten characters of
the caption with spacing removed -- the screen renders `#短发 #lwl` and the
share text writes `# 短发 # lwl` for the same post, and the share text
truncates a long caption. Rows with two different video ids are never folded:
an id is proof of two videos, and one author posting the same title twice is
ordinary.

**Where the id comes from.** A Douyin share link is `v.douyin.com/XXXX` and
carries no id; following its redirect yields `iesdouyin.com/share/video/<id>/`
— or the `note` form for a 图文 post, or `?modal_id=` when the post was opened
over its author's page — and that id is the record.

Many links landing on one id is expected here, and is not guarded against. It
is the same phenomenon as the repeated rows above: one run copied 晒月亮
(`shares 3,629`, the post the run log shows the loop spinning on) 130 times.
Two guards were built on the theory that a repeated id meant Douyin had begun
redirecting every request to a single fallback page under a rate limit. It had
not. The first refused real rows. The second deadlocked resolution completely,
because the pending queue is walked in the same order every pass and a refusal
at its head never clears — 228 links sat unresolved for a day behind three of
them. A repair command written to undo the imagined damage did real damage: it
returned 214 correctly resolved links to pending.

All three are gone. What remains is what was actually true: a pause between
requests, and a link left pending rather than written with a guess. The
collection deliberately produces many links per video, so the same value twice
is this data's normal shape and is never on its own evidence of a fault.

### 3b. The page is the authority; the screen corroborates

The phone reaches posts a web search will not return, and that is the only
reason it collects at all. But it reads a feed: it sees a post for a second or
two, at whatever moment the loop looked, and whatever it read has to be
stitched to a copied link afterwards. Every wrong row in this study came out
of that stitch — one video's counts beside another's caption, a neighbouring
author's 抖音号, a caption that had not drawn yet.

A page fetched from the video's own URL needs no stitch: the id is in the
address, so what is parsed out of the response belongs to that id by
construction. `python -m app.fetch_videos --apply` reads each collected
video's page into `web_videos`, and `python -m app.fetch_authors --apply`
reads each author's profile into `web_authors` — one visit per account,
because the 抖音号 is a property of the account and is on the profile and
nowhere else.

Where a page has been read it overrules the screen on the dashboard, and the
row says so (`read from the page`, and `from the page` under the publication
time). The screen reading is kept, not replaced: the two are different
observations — what a viewer saw in the app, and what the site served to a
fetch — and a study about removals should be able to show both.

**A page that answers is not the same as a page that answers about this
video.** Douyin serves a request for a removed video by playing the next
recommended one: status 200, no removal wording anywhere on it, and an API
response describing a different video entirely. One run stored "Johnny Dear —
第一颗纽扣错了", with that video's caption, author and 5,421 likes, against the
id of a video that was gone.

Nothing in the page finds this, which is why classification cannot rest on
page wording alone. What finds it is that the record came back carrying
someone else's `aweme_id` — a fact about the exchange, not about the text. So
`app.fetch_videos` checks the id it asked for against the id it got, stores
nothing from a mismatch, and files the mismatch as a check whose
`LinkCheck.evidence` reads `served another video`. `classify` reads evidence
ahead of markers for exactly this reason, and the removal reaches the
findings.

This also makes the signed-in browser the better takedown probe for Douyin.
The anonymous fetch in `app.recheck` is answered with a download wall, which
is no evidence either way; here the exchange either returns the video asked
for or it does not.

And no evidence either way must be recorded as that. The download wall is a
200 with no wording about the video, so the ordinary "it loaded, so it is
alive" reading called it `alive` — three Douyin checks were filed that way,
one of them for a video that had already been taken down. A survival invented
from a page that never named the video is worse than no observation, because
the survival curve is computed from these rows and nothing downstream can
tell the invented ones apart. So a Douyin check that reaches 200 with nothing
to read is `unknown`, and only `LinkCheck.evidence` — the id the site actually
served — can say `alive`. The visible effect is a Douyin takedown rate
computed over fewer checks than were made, which is the honest number.

**The fetch is made by a signed-in browser.** Douyin's own pages render in
the browser and gate a great deal behind a session — a profile fetched without
cookies is a download prompt — and a run of requests eventually meets a
verification page rather than a video. `python -m app.login` opens a browser
once, the researcher signs in by hand, and the session persists in a profile
directory that every later run reuses. No credential is read, typed or stored
by this code; what persists is what the site itself writes, as in any browser.

The window is visible on purpose. A verification page is something a person
can answer and a script cannot, so a run pauses for it instead of retrying —
retrying a challenge is how a session becomes a block. `--anonymous` still
fetches the share host with no session, which reads much less but touches no
account.

Which account does the fetching is a methodological choice, not a detail.
Every request carries the signed-in identity, and this study is about what a
platform removes from a community it polices. A research account used for
nothing else keeps the collection off a personal one; `--profile DIR` keeps
several apart, and the directory is never committed.

`parsed_by` records how a row was read. `embedded` means it came out of the
page's own data; `surface` means only the visible text and meta tags could be
read, which yields a caption and a date but no counts. A row parsed off the
surface is worth less and says so without being re-fetched. A page that could
not be read at all is stored with its status and error rather than left
looking like one never tried.

### 3. Pairing is exact, or it does not happen

A shared link is attached to a captured post only when the device harvested
that link from that post — the share sheet was opened on it, so the
association is a fact the phone observed, not an inference. That is the
`linked (exact)` label.

Matching on time alone is disabled (`pairing_window_seconds = 0`). It existed
for links copied by hand, and the assisted loop broke it: the loop copies a
link about two seconds after a post reaches the screen, at a steady cadence,
so once the ordering slipped by one, nearest-in-time matched every later post
to the link belonging to the one before it. The table then read

    id ...819109   @handle 晒月亮   name 想吃什么月亮
                   41K / 187 / 3,629   "你最忘不了哪一任 #lwl"

one video's engagement beside another's caption, with nothing on the row
saying so. An association that is wrong invisibly is worse than none:
unlinked rows announce what they lack.

`python -m app.pairing --undo-time-pairings` takes back the ids already
attached that way. Nothing is deleted — the post keeps what it read off the
screen, the link keeps its id and its share text, and they stand as two rows
rather than one row that mixes them.

**The name and the caption are safe.** Both come out of the same copied blob
(`【<author>的作品】<caption>`), so whatever else a link row lacks, those two
belong to each other and to the id beside them.

**A display name is not a handle.** On Douyin the handle is the 抖音号 and it
lives on the author's profile, which the loop does not open. The parser falls
back to the display name, so the dashboard shows a handle only when it differs
from the name — a name printed in the handle column implies an identifier the
row does not have.

### 3b. On Douyin, the handle is a nickname

`author_handle` means different things on the two phone platforms, and a
write-up that treats the column as one thing will overstate what it has.

TikTok renders an `@handle` that is unique and stable: it is the account, and
it can be typed into a URL. Douyin's stable identifier is the 抖音号, which the
feed never shows — it is on the profile page, one tap past anything this
instrument sees. What the feed shows is `@昵称`, a display name.

The column takes the 抖音号 when it happens to be on screen and the `@名字`
otherwise. That is the identifier the platform uses in practice — it is what
search accepts and what an author would be approached through — and leaving the
column empty would not have been more honest, only emptier. But two Douyin
accounts can carry the same nickname, and one account can change its nickname
between the day a video was collected and the day someone tries to contact its
author.

So for recruitment: the **video link** is the identifier that cannot drift, and
the handle is the human-readable route to the same place. Reach an author
through the link, and read the 抖音号 off the profile page at that point if the
account needs to be recorded stably.

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

`女同性恋` is unambiguous; every other term needs a qualification. Two attempts
were needed, and the first one failed instructively.

**Attempt one: name the collisions.** Adjacent-character boundaries for 拉拉 and
女同, plus context rules for 百合. This is also where an earlier version was
outright wrong: listed bare as a topic term, 拉拉 matched inside 拉拉裤 and then
*overrode* the exclusion written to catch it, so every packet of nappies stayed
in the corpus. But the deeper problem was that the list does not converge. One
real run produced 拉拉車 (a tour trolley), 拉拉山 (a mountain), 拉拉秧 (a weed),
傲拉拉 and 朵拉拉 (channel names), 拉諾拉拉庫 (Rano Raraku), 鬍子拉拉, 烤拉拉,
拉拉草莓, and 女同 inside 父女同框, 母女同囚, 仔女同住 and 呀女同我講. Every
run adds more.

**Attempt two: require two signals.** A term either qualifies on its own or it
is ambiguous and needs a companion beside it (`喜欢女`, `女朋友`, `情侣`,
`彩虹`, `同性`, `两个女生`, `监护`…). In that run every genuinely relevant row
carried a second marker and not one of the collisions did. A blocklist chases
instances; this states what on-topic text looks like.

**Attempt three: apply it only where it is needed.** Attempt two was applied to
`拉拉`, `女同` and `百合` alike, and in-scope fell from 267 rows to 6 out of 561.
So `女同` and `百合` were allowed to count alone again, on the reasoning that
their polluters had rules of their own.

**Attempt four: they did not.** Reading the 47 rows that reading admitted found
3 correct. `百合` is the ordinary Chinese word for the lily, and `FOOD` catches
recipes but not gardening, church hymns, a dance troupe, jewellery, a Go
tournament sponsor (梦百合杯), or a person's name (百合建房进度 · 百合才有家).
`女同` likewise appears inside Cantonese `同` meaning *with*: 個女同肚入面個B.

So `拉拉`, `女同` and `百合` all need a companion, and the reason is the
reader's own observation rather than a rule of thumb: **the relevant rows carry
several related terms at once and the collisions carry exactly one.**
`百合 + 短剧`, `百合 + GL`, `拉拉 + lesbian`, `女同 + 情侣` are the topic;
`百合` beside nothing is a flower. Genre markers are therefore companions, not
exclusions — except `动漫`, which is any cartoon and rescued 巴拉拉小魔仙, a
children's show whose title merely contains 拉拉.

**Only an unambiguous term may override a collision rule.** A soft exclusion
names a word the keyword hides inside, so a term that a companion merely
*confirmed* must not overrule it. Letting it re-created the original bug in a
new place: 拉拉 beside 动漫 read as on topic and overrode the very rule written
to catch 巴拉拉. `lesbian`, `女同性恋`, `出柜`, `是拉拉` may override a
collision; `拉拉` plus a companion may not. This shape — a term serving as both
the signal and the collision — has now caused three separate bugs, and it is
worth naming as a category rather than fixing case by case.

Four attempts, three of which over- or under-corrected. Each was a reasonable
reading of the errors then visible, and the corrections came from reading
sampled captions rather than from reasoning about the terms. This is calibration
against observed data and should be described that way, with the review counts
(47 in scope, 3 correct) reported as the evidence for the final rule.

The sequence is worth reporting as it happened. Each attempt was a reasonable
reading of the errors then visible, and each over- or under-corrected until the
categories were separated enough to treat differently. A filter arrived at this
way should be described as calibrated against observed data, not derived.

The companion list had to be narrowed once already: bare `女生` admitted
`港女同內地女生有咩分別` — girls from two cities. What signals the topic is a
*relation* to women, not a mention of them.

**Japanese was the largest single error, and the subtlest.** 百合 is the
Japanese word for the same genre, and Japanese writes it with the same
characters, so a "contains CJK ideographs" test called every Japanese yuri
video Chinese. One run put about a hundred of them in scope — Vtubers, anime,
and 百合ヶ浜, a beach. Kana is the reliable separator: Chinese uses no hiragana
or katakana at all. A methods section should name this, because "the text
contains Chinese characters" is a test that looks correct and is not one.

Exclusion reasons, all of which hide the row:

| reason | what it catches |
| --- | --- |
| `advertising` | escort bait: a booking phrase plus a Telegram or WeChat contact |
| `ai generated` | synthetic, so no author an interview could follow up |
| `fiction` | **a label, not an exclusion.** Short dramas, novels, audio dramas, comics, edits. WLW fiction is Chinese WLW content and its removal is the same event this study measures, so it belongs in the corpus. It was excluded for a while on the argument that fiction has no author to interview — an argument that bears on the interview half of the study, not on what counts as a takedown, and the corpus is the wrong place to enforce it. The label stays so the two can be separated in analysis |
| `games and toys` | where 拉拉 turns up as a character or a brand: 拉拉公主, 拉拉管玩具, NPC walkthroughs |
| `divination` | 紫微斗数, 八字, 塔罗, 风水 — a genre where 女同志 means "female client". Hard rather than soft, because the case that prompted it carried a topic term and still had to go |
| `unrelated product` | 拉拉 inside a brand or product name |
| `not about the topic` | 女同 inside a word about a classmate or colleague |
| `gossip` | 八卦, 吃瓜 — soft, since gossip about a lesbian public figure carries a term of its own |
| `not wlw` | male-only content reaching in through a shared term |
| `not in chinese` | the study is of Chinese-language content |
| `no topic term` | nothing placed it on topic |
| `no text` | the parser read no caption |

Not every reason hides a row: `fiction` is a label, and rows carrying it are in
the corpus. `HIDDEN` is the set that hides.

**Rows are marked, never dropped.** A video a filter deletes is a video whose
disappearance can never be observed, and nothing in the data would show it had
been there — the one failure a takedown study cannot detect after the fact.
The capture dashboard lists each
reason with its count and lets one be read on its own (`?show=fiction`,
`?show=excluded`, `?show=all`), because a filter is only worth trusting once
someone has read what it removed — and reading 500 mixed rows is not reading.

The **CSV export carries the corpus**, not everything collected: it is what an
analysis actually reads, and `?show=all` still exports the rest. Excluded from
a deliverable is not the same as deleted, and `app/views.py::in_scope_filter`
is the single definition both the dashboard and the export use — they had
already drifted once, with the export dropping hand-collected rows the
dashboard kept.

**One carve-out**, in `app/views.py`: a Douyin or TikTok row whose link was
copied by hand is never hidden. Those were chosen one at a time by a person,
and their captions are frequently truncated to `...more` or absent, so the text
is no evidence about the video. They are also the rows that cost the most to
collect. YouTube gets no such exemption — the API chose those results, not a
person.

**Recall is the risk this design takes on**, and the two-signal rule raises it
deliberately: a genuinely relevant video whose text carries only `拉拉` and
nothing else is excluded. That price was accepted for precision, and it is
visible — the excluded rows are listed by reason. A term missing from the topic
list excludes real videos too. It is survivable because the verbatim payload is kept for
every observation: `python -m app.relevance` re-marks the whole corpus from it,
so a corrected rule reaches rows collected weeks earlier and nothing has to be
collected again. Check a rule against text without touching the database, or read what a
category actually caught:

```
./.venv/bin/python -m app.relevance --test "百合短剧 治愈女同"
./.venv/bin/python -m app.relevance --test-file captions.txt
./.venv/bin/python -m app.relevance --sample "no topic term" --limit 40
```

`--sample` exists because counts and captions answer different questions: the
counts say how much each rule caught, and only the captions say whether it
caught the right things. `no topic term` is the bucket to read first — it is
where a real video lands when the rules do not recognise how it described
itself.

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

### 11. The topic filter runs on YouTube and TikTok, not on Douyin

Section 10 describes a filter built for one sampling frame and then applied to
all of them. That was wrong, and the first Douyin collection said so
immediately: every row came back marked `no topic term`.

The captions were these.

| caption | marked |
| --- | --- |
| 许愿这次别再丢下我#lwl#lwl | no topic term |
| 今夜的风悄悄月悄悄 吻你的眉梢#lwl | no topic term |
| 如果我想让你只属于我，你会不会觉得我太自私 #lwl #萌t | no topic term |

These are on topic. They say so with a community tag rather than with a term
the filter knows, and a lyric about someone's girlfriend does not have to
announce its subject to be about it. Filtering them hid the platform entirely —
and with it the video ids, which are what a takedown study re-checks.

**The distinction is the sampling frame, not the language.** A YouTube keyword
search returns whatever the API matched: 女同性恋 surfaces Japanese drama,
divination lessons and 货拉拉 delivery ads, and about 6% of what comes back is
in scope. Douyin is searched by hand for community hashtags — `#lwl`, `#wlw`,
`#les` — which are not fragments of ordinary words but labels the community
applies to its own posts. There the search *is* the filter, and a second one
only removes real data.

The three frames therefore get three policies, in `FILTER_POLICY`:

| platform | policy | what runs |
| --- | --- | --- |
| YouTube | `full` | hard exclusions, Chinese-language requirement, **and a topic term must be present** |
| TikTok | `search` | hard exclusions and keyword-collision rules only — no language test, no topic term |
| Douyin | `tags` | nothing, except that the caption must carry a community tag |

TikTok was `language` first, on the assumption that a search there behaves
like a Douyin one with a language problem attached: same community terms, so
drop the topic-term rule, but keep the requirement that the caption be in
Chinese. The first real search said otherwise. 女同性恋, 女同 and 拉拉 on the
international build return every language at once and very little of this
study's population; the terms that reach it name it directly — `Chinese
lesbian`, 中国女同性恋, 中国女同 — and what they surface is Chinese and
diaspora creators who caption in English.

Against that sample a language test does not remove noise, it removes the
sample. The search has already said "Chinese"; asking the caption to say it
again in Chinese characters throws away the creators the search was chosen to
find. So on TikTok both the language rule and the topic-term rule go, and what
remains is the collision rules: a 货拉拉 delivery ad, a divination channel,
Japanese yuri (kana is a hard exclusion, unaffected by this) and male-only
content are still out, and fiction is still labelled.

**This makes TikTok a third population, not more of the same one.** Douyin is
mainland, Chinese-language, inside the censorship regime this study is about.
TikTok here is largely diaspora, often English-captioned, moderated by a
different company under different law. A takedown rate pooled over the two
describes neither, and the difference between them is not a finding about
censorship until everything else that differs has been accounted for. Report
them separately, and say in the methods section which search terms produced
each — on TikTok the term is not incidental to the sample, it *is* the sample
definition. `TikTokSearchParser` records it on every row (`feed` reads
`search:<query>:<sort>`), so the claim is checkable against the data rather
than resting on someone's memory of what they typed.

**Douyin's one rule is the same argument, stated exactly.** The reason Douyin
runs no topic filter is that `#lwl`, `#wlw` and `#les` are labels the community
attaches to its own posts, so the search already did the work. That is a claim
about the *tag*. A post reached by a hashtag search whose caption carries no
hashtag got there by matching something else — and on this corpus that
something else is the poster's display name. Accounts called LWL, lwl6依然,
▓ Lwl . ▓, whose captions are 上班容易吗, 出海打鱼, 为什么啊, 延吉海兰台. So the
caption must carry a community tag, and nothing else is asked of it: no
language test, no topic term, no judgement about the text.

That is stricter than it first looks, and deliberately so. It also excludes
第一次追女孩子到手了 — an account called LWL writing about pursuing a girl, which
an earlier version of this rule kept on the grounds that the caption is about
the topic. The strict version is the only one that can be stated without
reference to who posted it, and the only one whose output can be checked
against the search that produced it.

Two things went wrong on the way, both worth recording because both were
invisible.

The rule was written once and matched nothing: `\blwl\b` finds none of
LWL出游随拍记录, LWL回顾经典百听不厌 or 威龙LWL6666668888, because Python counts CJK as
word characters and there is no word boundary between `LWL` and `出`. A filter
that silently excludes nothing reads exactly like a filter that found nothing
to exclude.

Then, corrected, it still marked nothing — because the corpus filter is a SQL
condition over the post tables, and every one of those captions was on a *link*
row, which has no post to be filtered. That gap had been there all along and
became total when the default listing changed to one row per link. The filter
now runs over the assembled rows as well.

**These rows are hidden, never deleted.** `app/prune.py` exempts this platform:
the rule is days old and has been rewritten twice, marking is reversible —
`python -m app.relevance` re-reads every stored payload — and deleting is not.

An unrecognised platform gets `full`. A new one that quietly collected
everything would be a change to the corpus definition that nobody decided on.

**What to report.** Douyin counts are counts of everything collected; YouTube
counts are counts of what survived a topic filter; TikTok counts are counts of
what a differently-worded search returned. None of the three are comparable,
and the dashboard says so on the page rather than leaving it to a footnote. The
precision of the Douyin sample rests on the hashtags chosen, which is a claim
about the search terms and belongs in the methods section next to them.

This is also the third time the same lesson has been recorded here: a rule
written from one platform's data was assumed to hold for another, and the data
said otherwise within one collection run. Twice now it was TikTok's row in this
very table — first the topic term, then the language test — written from
reasoning about the platform rather than from a search actually run on it. The verbatim payload is what made the
correction free — `python -m app.relevance` re-marked the whole corpus, and
nothing had to be collected again.


### 12. The video file is kept, because a removal destroys the evidence

The re-check establishes *that* a video went. It says nothing about what went:
not the footage, not the frames, not what was said. Every question of the form
"what kind of video gets removed" — which is the analytical question this
corpus exists for — needs the video, and a takedown is precisely the moment it
stops being available to anyone.

So `python -m app.download_videos --apply` keeps a copy, and it runs on the
same day as the collection rather than at the end of the study. Of one
evening's 73 Douyin videos, 8 were gone within hours of being posted. Those
eight can no longer be analysed by anyone; a copy taken that evening would
have been the only one in existence.

**How, and why not with an off-the-shelf tool.** The obvious candidates are
Windows-only GUI programs distributed as binaries with no source in the
repository, which cannot be run here, cannot be audited, and would be pointed
at a signed-in account. Nothing new is needed anyway: the signed-in browser
already captures Douyin's own API answer, and the file addresses are inside
it. They are fetched through the browser's own request context, so the
cookies, the user agent and the referer are the ones the site just served the
page to — a plain HTTP request for the same address is answered with a short
error body instead.

Three things guard the folder, each for a failure already seen in this
project:

- **The id is checked before anything is downloaded.** A request for a removed
  video is answered with the next recommended video's record, whose addresses
  work perfectly well — they are simply not this video. Without the check the
  folder fills with other people's footage filed under the ids of the removed
  ones, which is worse than a gap because nothing downstream can tell.
- **The bytes are checked to be a video.** An error page saved as `<id>.mp4`
  gives a folder that looks complete and a corpus that is not, discovered at
  the point of analysis, when the original is gone.
- **The digest is recorded.** `file_sha256` makes a later claim checkable: the
  copy analysed is provably the copy downloaded. That matters most for exactly
  the videos whose originals can no longer be compared against.

The files live outside the database and outside the repository, and the row
records the path rather than the bytes. A moved or emptied folder is therefore
not corruption — re-running the download refills it and skips what is already
held.

**What to report.** The download is not a measurement and never feeds a rate.
It is preservation, and the thing to say in the methods section is when it ran
relative to collection, since a video removed before the copy was taken is
absent from the analysis while still being present in the takedown count. That
asymmetry is a property of the archive, not of the platform.


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

**Holding copies of the videos raises its own questions**, separate from the
collection ones above, and the application should answer them rather than
leave them to the reader:

- The copies are of public posts, kept for analysis and not redistributed.
  Nothing in this pipeline publishes them, and the folder sits outside the
  repository so that no ordinary `git add` can.
- Some of the people in them will later have removed the video themselves.
  A deletion by its author is a wish about the material, and an archive that
  ignores it is doing something the platform's own removal is not. Say what
  happens when an interviewee asks for their copy to be destroyed — the answer
  should be that it is, and `local_path` makes that one file to delete.
- Retention has an end. Name it, and name where the folder lives and who can
  reach it; a laptop's Documents directory is a real answer only if the disk
  is encrypted and the machine is the researcher's own.
- The fetches carry the researcher's signed-in identity. A separate research
  account keeps the collection off a personal one and is easier to describe
  here.
