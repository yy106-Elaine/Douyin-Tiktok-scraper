# Architecture

```
Douyin / TikTok on a study phone
        │  (accessibility events, capped at 2 reads/second)
        ▼
CaptureAccessibilityService  ──►  CaptureBuffer  (merge partial reads,
        │                                          finalise after 5s idle)
        ▼
Room database `captures`  (offline queue, survives reboots)
        │  (SyncWorker, ≤200 rows per request, X-API-Key)
        ▼
POST /api/captures/batch
        │
        ├──►  capture_events   verbatim JSON, one row per post per day
        └──►  douyin_posts / tiktok_posts   typed columns for analysis

Participant taps Share → "Save link for research"
        │
        ▼
POST /api/links/shared  ──►  shared_links  ──►  pairing  ──►  video_id, video_url
```

## Why the two halves exist

The accessibility tree gives engagement counts but **never a video id**. The
share sheet gives a real URL but no counts. Neither is sufficient alone, so
the system collects both and joins them afterwards (`app/pairing.py`).

## The three-step platform registry

Adding a platform touches exactly three files:

1. `backend/app/platforms.py` — map the Android package name to a slug.
2. `backend/app/models.py` — add a `_PostMixin` table for it.
3. `backend/app/parsers/__init__.py` — register `(model, structure_fn)`.

On the device, add a `PostParser` implementation and register it in
`CaptureAccessibilityService.parsers`, and add the package name to
`res/xml/accessibility_service_config.xml`.

## Deliberate choices worth knowing

**Counts are uploaded as displayed strings.** `"12.3万"` travels to the server
as `"12.3万"`, not as `123000`. Converting on the device would destroy the
evidence that the value was abbreviated. The server converts and sets
`counts_approximate`.

**`packageNames` is set in the service config.** The system then delivers
events only for Douyin and TikTok, so the service is structurally incapable of
observing banking apps, messages, or anything else on the participant's phone.
This is a claim you can make in a consent form and defend in an IRB review.

**The device id is a random UUID**, generated on first launch. No IMEI, no
advertising id, no hardware identifier.

**Sync uses WorkManager, not a foreground service.** Uploads are not
time-critical, and letting Android batch them keeps the app off the
battery-usage screen — which matters when a participant carries the phone for
weeks.

**Deduplication is per post, per participant, per day.** Scrolling past the
same video twice in an afternoon produces one row. Seeing it again next week
produces a second row, which is what you want for exposure-over-time analysis.
