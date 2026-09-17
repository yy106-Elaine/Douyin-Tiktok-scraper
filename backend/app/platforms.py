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
