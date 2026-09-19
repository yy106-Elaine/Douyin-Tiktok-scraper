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

#: How much of `app/relevance.py` each platform's rows are put
#: through. The right amount depends on the sampling frame, not on the
#: language, and the three frames here differ.
#:
#: "full" -- YouTube. A keyword search returns whatever the API
#: matched: 女同性恋 surfaces Japanese drama, divination lessons and
#: 货拉拉 delivery ads, and about 6% of what comes back is in scope. The
#: text has to earn its place, so a topic term is required.
#:
#: "language" -- TikTok. Searched by hand for community terms, so the
#: search is already doing the topic work; but it is the international
#: build, a search there returns other languages, and this study is
#: about Chinese-language content. So the language requirement stays
#: and the topic-term requirement goes.
#:
#: "none" -- Douyin. Sampled from community hashtags (#lwl, #wlw, #les)
#: which are labels the community puts on its own posts, not fragments
#: of ordinary words. The first Douyin collection had every row marked
#: `no topic term` -- 许愿这次别再丢下我#lwl, 今夜的风悄悄月悄悄 吻你的眉梢#lwl --
#: which hid the whole platform, and the video ids with it. A
#: mainland-only app needs no language test either.
FILTER_POLICY: dict[str, str] = {
    "youtube": "full",
    "tiktok": "language",
    "tiktok_lite": "language",
    "douyin": "none",
    "douyin_lite": "none",
}


def filter_policy(platform: str | None) -> str:
    """Unknown platforms get the strictest policy, never the loosest.

    A new platform that quietly collected everything would be a change
    to the corpus definition that nobody decided on.
    """
    return FILTER_POLICY.get((platform or "").lower(), "full")


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
