# Verifying and repairing parser selectors

The on-device parsers read view ids and UI strings that belong to one build of
one app. **Re-verify before every collection wave.** A broken selector produces
empty fields rather than an error.

## Dump the current screen

With the phone connected and the target post on screen:

```bash
adb shell uiautomator dump /sdcard/window_dump.xml
adb pull /sdcard/window_dump.xml .
```

Open the XML and look at `resource-id`, `text`, and `content-desc`. Android
Studio's Layout Inspector shows the same tree interactively.

## Map what you find onto the parser

Each parser keeps every selector in a `private companion object` at the top of
the file — that block is the only thing you should need to edit.

| Field | TikTok (English, checked) | Douyin (Chinese, **unverified**) |
|---|---|---|
| post boundary | view id contains `widget_container` | view id contains `video_container` |
| author | `content-desc` matching `X profile`, else view id `/title` | `@handle` in text |
| caption | view id containing `desc`, else longest undescribed text ≥30 chars | same, ≥8 chars |
| likes | `Like video. N likes` | `点赞N` / `N次点赞` |
| comments | `Read or add comments. N comments` | `评论N` / `N条评论` |
| shares | `Share video. N shares` | `分享N` / `转发N` |
| saves | first number **nested under** the node described `Favorites` | `收藏N` |
| music | `Sound: X` | `X创作的原声` |
| feed | selected tab: `For You` / `Following` | `推荐` / `关注` |

Package names matter and are not guessable: TikTok Lite is
**`com.tiktok.lite.go`**, not a `.go` suffix on the main package. All four are
listed in `accessibility_service_config.xml`.

Every TikTok row above is confirmed against a working collector. **No Douyin
row is.** Treat the Douyin column as a starting hypothesis.

## Check the guard too

`shouldSkip()` detects the comment sheet. If its strings go stale the parser
starts reading comments as captions — a silent data-quality failure that is
worse than collecting nothing. Verify it by opening the comment sheet and
confirming no rows appear.

## Known-harder cases

**Lite builds** label their action buttons poorly: on TikTok Lite the four
counts are bare `TextView`s inside clickable buttons with a shared generic
icon description, so they cannot be told apart by description at all. A
working collector resolves them by vertical screen position in TikTok's fixed
Like / Comment / Favorite / Share order — effective, but it silently mislabels
every count the moment that order changes. This project instead returns null
for counts it cannot identify with confidence, so prefer the **full** app on
study devices, where the descriptions are unambiguous.

**Douyin count ordering** varies between builds — both `点赞12.3万` and
`12.3万次点赞` appear, which is why `DouyinParser` uses two-alternative
patterns and takes whichever group matched.
