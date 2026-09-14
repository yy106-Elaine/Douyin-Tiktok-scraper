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

| Field | TikTok (English) | Douyin (Chinese) |
|---|---|---|
| author | `content-desc` ending `'s profile` | `@handle` in text |
| caption | `resource-id` ending `/desc`, else longest undescribed text | same |
| likes | `Like video. N likes` | `点赞N` / `N次点赞` |
| comments | `N comments` | `评论N` / `N条评论` |
| shares | `N shares` | `分享N` / `转发N` |
| saves | `N favorites` | `收藏N` |
| feed | `For You` / `Following` | `推荐` / `关注` |

## Check the guard too

`shouldSkip()` detects the comment sheet. If its strings go stale the parser
starts reading comments as captions — a silent data-quality failure that is
worse than collecting nothing. Verify it by opening the comment sheet and
confirming no rows appear.

## Known-harder cases

**Lite builds** label their action buttons poorly. Rather than guessing by
on-screen position (fragile, and wrong the moment the layout changes), these
parsers return null for fields they cannot identify with confidence. Prefer
the full app on study devices.

**Douyin count ordering** varies between builds — both `点赞12.3万` and
`12.3万次点赞` appear, which is why `DouyinParser` uses two-alternative
patterns and takes whichever group matched.
