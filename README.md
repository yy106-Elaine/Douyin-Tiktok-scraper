# Douyin / TikTok exposure capture

Research tooling for recording which Douyin and TikTok posts appear on a
participant's phone, and what metadata was displayed alongside them.

Two halves:

- **`android/`** — a Kotlin app that reads the two feeds via Android's
  accessibility service and queues observations offline.
- **`backend/`** — a FastAPI service that ingests batched observations,
  structures them per platform, and exports CSV.

Collected per post: author, caption, music, feed tab, like / comment / share /
save counts, ad and AI-generated markers, and — for posts the participant
shares into the app — the real video id and web URL.

**Not collected:** comment text, video files, direct messages, or anything
from any other app.

## Status

| Part | State |
|---|---|
| Backend + dashboard | Complete, 35 tests passing |
| Android data flow, buffering, sync, share capture | Complete, 22 JVM tests passing |
| TikTok parser selectors | Cross-checked against a working collector; re-verify per app version |
| Douyin parser selectors | **Unverified — hypotheses only** |

No Douyin selector in this repository has been confirmed against a device.
Dump the tree and correct them before collecting anything:
[`docs/SELECTORS.md`](docs/SELECTORS.md).

## Backend quickstart

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # set ADMIN_API_KEY to a long random string
./.venv/bin/python -m pytest  # 24 tests
./.venv/bin/uvicorn app.main:app --reload
```

Add participants to `approved_participants.csv` — only listed emails can
register:

```csv
email,participant_id,note
someone@example.edu,P001,pilot
```

Defaults to SQLite. For MySQL, set `DATABASE_URL` in `.env`.

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | none | Exchange an approved email for an API key |
| POST | `/api/captures/batch` | participant key | Upload ≤200 observations |
| POST | `/api/links/shared` | participant key | Submit a shared link, pair it to a post |
| GET | `/api/export/posts.csv?platform=douyin` | admin key | Export structured rows |
| GET | `/dashboard?platform=douyin` | admin key | Web view of what has been captured |

The dashboard also accepts the admin key as `?key=...`, since a browser cannot
set a header from the address bar. That puts the key in browser history and
server logs — serve it over HTTPS and treat the URL as a credential.

```bash
curl -H "X-API-Key: $ADMIN_API_KEY" \
  "http://localhost:8000/api/export/posts.csv?platform=douyin" -o douyin.csv
```

## Getting the app onto a phone

**You do not need Android Studio.** Every push rebuilds the APK in CI and
attaches it to the repository's **Latest debug APK** release — open that page
in the phone's browser and download it directly.

To build locally instead (requires the Android SDK; `minSdk` 26):

```bash
cd android
./gradlew assembleDebug -PbackendBaseUrl=https://your-server.example
adb install app/build/outputs/apk/debug/app-debug.apk
./gradlew test    # 22 JVM tests, no device needed
```

The backend address is also editable on the phone at registration, so the
build-time default only sets the pre-filled value.

**For a first run on a phone, follow [`docs/TESTING.md`](docs/TESTING.md)**
step by step — including how to calibrate the Douyin parser, which will not
work until you do.

On the phone: open the app → **Register device** (enter an approved email and
the server address) → **Enable capture service** → turn the service on in
Android's accessibility settings.

To capture a video's URL, the participant shares it from Douyin or TikTok and
picks **"Save link for research"**.

## How to read the data

`capture_events` holds every observation verbatim, so a parser bug can be
fixed by re-parsing rather than re-collecting. `douyin_posts` and
`tiktok_posts` hold typed columns for analysis.

**Before analysing anything, read
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).** It covers the limitations that
belong in a write-up: counts are abbreviated and approximate, most posts have
no video id, pairing is heuristic, and parsers fail silently when an app
updates.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the pieces fit, and why
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — limitations, ethics, what to report
- [`docs/SELECTORS.md`](docs/SELECTORS.md) — verifying parsers against a device
- [`docs/TESTING.md`](docs/TESTING.md) — first run on a phone, step by step

## Attribution

The architecture follows [tracely](https://github.com/bellesea/tracely) and
[screen_logger](https://github.com/bellesea/screen_logger) by
[Belle](https://github.com/bellesea). No code was copied — see
[`ATTRIBUTION.md`](ATTRIBUTION.md).

## Licence

MIT — see [`LICENSE`](LICENSE).
