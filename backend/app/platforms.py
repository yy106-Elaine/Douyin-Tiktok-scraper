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
#: "chinese-wlw" -- TikTok. Searched by hand, so neither a topic term
#: nor Chinese characters are required in the way the stricter
#: policies require them. What is required is that the caption name
#: both halves of the population: something Chinese and something
#: WLW, in any language.
#:
#: Because the search term names the population and the results do
#: not obey it. `Chinese lesbian` returns `#butchfemme #femme4butch
#: #lesbiansoftiktok`, `opposites attract #wlw #wlwcouple`, `Plz
#: laugh #rockclimb #lesbian #wlw` -- real lesbian content, a
#: different population, and a rate computed over whatever else the
#: recommender attached to the query is a rate for that other thing.
#: Of 104 videos collected this way, 19 were of this kind.
#:
#: English is fine and always was: what this reaches is largely
#: diaspora creators captioning in English, so the Chinese half may
#: be Chinese characters or the words those creators write --
#: including in Portuguese and Spanish, which the search also
#: reaches.
#:
#: This started as "language", which required Chinese. What that
#: assumed was a TikTok search behaving like Douyin's, and it does
#: not: 女同性恋, 女同, 拉拉 on the international build return every
#: language at once and almost nothing from the population this
#: study is about. The terms that do work name it directly --
#: `Chinese lesbian`, 中国女同性恋, 中国女同 -- and what they surface
#: is Chinese and diaspora creators who caption in English. A
#: language test would have thrown that away as noise, which is the
#: opposite of what it is: the search already said "Chinese".
#:
#: The collision rules still apply, so a 货拉拉 delivery ad, a
#: divination channel, Japanese yuri (kana is a hard exclusion) and
#: male-only content are still out, and fiction is still labelled.
#: What goes is only the requirement that the caption itself prove
#: the language and the topic.
#:
#: Read the two platforms as two populations, not one. Douyin is
#: mainland, Chinese-language, inside the censorship regime being
#: measured; TikTok here is largely diaspora, often English-captioned,
#: under a different moderation system. A takedown rate pooled over
#: both describes neither -- see docs/METHODOLOGY.md.
#:
#: "none" -- Douyin. Sampled from community hashtags (#lwl, #wlw, #les)
#: which are labels the community puts on its own posts, not fragments
#: of ordinary words. The first Douyin collection had every row marked
#: `no topic term` -- 许愿这次别再丢下我#lwl, 今夜的风悄悄月悄悄 吻你的眉梢#lwl --
#: which hid the whole platform, and the video ids with it. A
#: mainland-only app needs no language test either.
FILTER_POLICY: dict[str, str] = {
    "youtube": "full",
    "tiktok": "chinese-wlw",
    "tiktok_lite": "chinese-wlw",
    "douyin": "tags",
    "douyin_lite": "tags",
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
