"""Android package name -> platform slug.

Adding a platform is a three-step change; see docs/ARCHITECTURE.md.
"""
from __future__ import annotations

PACKAGE_TO_PLATFORM: dict[str, str] = {
    # Douyin (mainland China build)
    "com.ss.android.ugc.aweme": "douyin",
    # Douyin Lite
    "com.ss.android.ugc.aweme.lite": "douyin_lite",
    # TikTok (international build)
    "com.zhiliaoapp.musically": "tiktok",
    # TikTok Lite
    "com.tiktok.lite.go": "tiktok_lite",
}

#: Platforms collected without a phone. YouTube is read through its own
#: Data API, so no Android package maps to it -- but everything
#: downstream (tables, dashboards, re-checking, export) is the same.
API_PLATFORMS: frozenset[str] = frozenset({"youtube"})

#: Platforms whose rows are put through the topic filter in
#: `app/relevance.py`.
#:
#: YouTube needs it and Douyin does not, and the reason is the sampling
#: frame rather than the language. A YouTube keyword search returns
#: whatever the API matched -- 女同性恋 surfaces Japanese drama, divination
#: videos and 货拉拉 delivery ads, and about 6% of what comes back is in
#: scope. Douyin is sampled from community hashtags: #lwl, #wlw, #les.
#: Those are not words that occur inside unrelated ones, they are tags
#: the community applies to its own posts, so the search itself is the
#: filter and a second one only removes real data.
#:
#: This was not a guess either way. The first Douyin collection had
#: every row marked "no topic term" -- captions like 许愿这次别再丢下我#lwl
#: and 今夜的风悄悄月悄悄 吻你的眉梢#lwl, which are plainly on topic and
#: say so with a tag rather than a term. Filtering them would have
#: hidden the entire platform, and the video ids with it.
#:
#: TikTok stays filtered even though it is searched by hand the same
#: way. The Douyin argument does not carry over: TikTok is the
#: international build, a search there returns other languages, and
#: this study is about Chinese-language WLW content. That is the
#: filter's original job and it still has it here.
FILTERED_PLATFORMS: frozenset[str] = frozenset(
    {"youtube", "tiktok", "tiktok_lite"}
)

# Platforms whose structured rows live in the same table.
PLATFORM_FAMILY: dict[str, str] = {
    "douyin": "douyin",
    "douyin_lite": "douyin",
    "tiktok": "tiktok",
    "tiktok_lite": "tiktok",
    "youtube": "youtube",
}


def platform_for_package(package: str) -> str | None:
    return PACKAGE_TO_PLATFORM.get(package)


def family_for_platform(platform: str) -> str | None:
    return PLATFORM_FAMILY.get(platform)
