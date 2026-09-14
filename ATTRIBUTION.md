# Attribution

The architecture of this project — an on-device accessibility-service
collector paired with a small server that ingests batched observations —
follows the design of **[tracely](https://github.com/bellesea/tracely)** and
**[screen_logger](https://github.com/bellesea/screen_logger)** by
[Belle (bellesea)](https://github.com/bellesea), which study Instagram and
TikTok exposure.

Specifically, the following design decisions are taken from that work:

- splitting collection (phone) from storage (server) and syncing in batches;
- using Android's accessibility service to observe feeds passively rather
  than automating the apps;
- buffering repeated partial reads of the same post and finalising once it
  settles;
- a per-participant API key issued against an approved-email whitelist;
- a platform registry so that adding a platform is a small, local change;
- isolating each post at its container view id, rather than parsing a screen
  as a single post.

The TikTok selector strings in `TikTokParser.kt` (the `Like video. N likes`
family of content descriptions, the `widget_container` post marker, and the
`com.tiktok.lite.go` package name) were cross-checked against tracely's
parser. Those are observable facts about TikTok's own interface rather than
authored expression, and the implementation around them is this project's.

**No code was copied.** At the time this project was written, neither source
repository carried a licence file, which means all rights were reserved and
reuse of their code would have required permission. Everything in this
repository was written from scratch against a description of the two systems;
the ideas above are architecture, which is not what copyright protects.

If you build on this work, please credit both projects. If Belle later adds an
open-source licence and you want to reuse the original code directly, that is a
separate and better-supported path than re-implementing it.
