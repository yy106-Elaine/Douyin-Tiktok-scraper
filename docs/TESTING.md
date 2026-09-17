# First run on a phone

A checklist for the first live test. Budget about an hour; the Douyin
calibration in step 7 is the part that actually takes time.

## What you need

- An Android phone (Android 8.0 / API 26 or newer) with Douyin and/or TikTok installed
- A laptop on the **same Wi-Fi** as the phone
- A USB cable, if you want the logs in step 7 — recommended

---

## 1. Start the backend on your laptop

```bash
cd Douyin-Tiktok-scraper/backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set a real admin key:

```
ADMIN_API_KEY=pick-a-long-random-string-here
```

Add yourself to `approved_participants.csv` — registration is refused for
anything not on this list:

```csv
email,participant_id,note
you@example.edu,P001,pilot
```

Start it listening on the network rather than only on localhost:

```bash
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 2. Find your laptop's address on the Wi-Fi

```bash
ipconfig getifaddr en0        # macOS Wi-Fi; try en1 if that is empty
```

You will get something like `192.168.1.42`. The phone will use
`http://192.168.1.42:8000`. Check it from the phone's browser before going
further — if that URL does not load, nothing else in this document will work,
and the cause is usually the laptop firewall or a guest network that isolates
devices from each other.

## 3. Get the APK onto the phone

On the **phone's** browser open the repository's Releases page and pick
**Latest debug APK**, then download the `.apk`. Android will ask permission to
install from this source; allow it for the browser.

The APK is rebuilt automatically on every push, so re-downloading from that
same page is how you pick up a fix.

## 4. Register the device

Open **Video Capture** → **Register device**:

- **Email** — the address you put in `approved_participants.csv`
- **Server** — `http://192.168.1.42:8000` (your address from step 2)

"Registered as P001" means the phone reached the backend and was issued a key.
"That email is not on the approved participant list" means the backend is
reachable but the CSV does not list you. "Could not reach the server" is a
network problem, back to step 2.

> Debug builds allow plain HTTP so this local setup works. Release builds
> require HTTPS — see `src/debug/res/xml/network_security_config.xml`.

## 5. Turn on capture

**Enable capture service** opens Android's accessibility settings. Find
**Video Capture** under *Downloaded apps* and switch it on.

Android will warn that the service can observe what you do. That is accurate:
it reads screen contents. It is restricted at the OS level to Douyin and
TikTok only — `android:packageNames` in the service config — so no other app is
observable.

## 6. Watch data arrive

Open Douyin or TikTok and scroll slowly through a handful of videos. Give it a
few seconds per video: a post is only recorded once it has been off screen for
5 seconds, which is how partial reads get merged into one row.

On your laptop, open:

```
http://localhost:8000/dashboard?key=YOUR_ADMIN_KEY
```

Rows should appear within a minute of scrolling. If the app's home screen shows
captures pending but the dashboard is empty, the phone is queuing but not
uploading — tap **Upload now** and check the server log.

## 7. Calibrate the Douyin parser

**The TikTok selectors are checked; the Douyin ones are guesses.** Expect empty
columns on the first run. This step fixes that.

Connect the phone by USB, enable USB debugging, then:

```bash
adb logcat -s VideoCapture
```

Scroll Douyin and read the log:

- `parsed douyin author=... likes=...` — a field with a value is working.
- `parsed douyin author=null likes=null` — the post was found, the fields were
  not. Selectors are wrong.
- `no post parsed; N text nodes` followed by a list of `id= text= desc=` — the
  post was not found at all. **That list is what you need**: it is every piece
  of text on screen with its view id and description.

Take that dump to `DouyinParser.kt`; every selector lives in the
`private companion object` at the top. Match the real `id=` / `desc=` values
against the patterns there and correct them. `docs/SELECTORS.md` explains what
each field should look like.

Also verify the guard: open a video's comment sheet and confirm the log says
`frame skipped: comment sheet open`. If it does not, comments will be recorded
as captions.

After editing, push the change — CI rebuilds the APK and you re-download it
from the same Releases page.

## 8. Test the link capture

In Douyin or TikTok, share a video → **Save link for research**. You should see
"Link saved", and the dashboard's **Shared links** table should show a new row:

- **paired** — matched to a post you had just scrolled past. This is the good case.
- **needs resolving** — a `v.douyin.com` short link with no video id yet.
- **unpaired** — no matching capture within ±15 minutes.

Share a video you viewed moments ago; sharing something from an hour ago will
correctly fail to pair.

---

## When something is wrong

| Symptom | Where to look |
|---|---|
| Registration fails, server unreachable | Same Wi-Fi? Laptop firewall? URL loads in the phone's browser? |
| Service on, nothing captured | `adb logcat -s VideoCapture` — is anything logged at all? |
| Every frame skipped | The comment-sheet guard is over-matching; see `shouldSkip` |
| Fields empty but posts found | Selectors are stale — step 7 |
| Captures pending but not uploading | Tap **Upload now**; check the uvicorn log for 401 (bad key) |
| Counts look rounded | Expected — they are read from the UI. See `docs/METHODOLOGY.md` |
