from app.links import canonical_url_for, extract


def test_full_tiktok_url_yields_id_and_handle():
    parsed = extract("look https://www.tiktok.com/@someuser/video/7301234567890123456")
    assert parsed.platform == "tiktok"
    assert parsed.video_id == "7301234567890123456"
    assert parsed.author_handle == "someuser"
    assert parsed.needs_resolution is False


def test_douyin_share_blob_yields_short_link():
    blob = "7.86 复制打开抖音，看看【小明的作品】 https://v.douyin.com/iRkQwBt/ 复制此链接"
    parsed = extract(blob)
    assert parsed.platform == "douyin"
    assert parsed.video_id is None
    assert parsed.needs_resolution is True
    assert parsed.raw_url == "https://v.douyin.com/iRkQwBt/"


def test_full_douyin_url():
    parsed = extract("https://www.douyin.com/video/7123456789012345678")
    assert parsed.platform == "douyin"
    assert parsed.video_id == "7123456789012345678"


def test_text_without_a_link():
    parsed = extract("just some words")
    assert parsed.platform is None
    assert parsed.needs_resolution is False


def test_canonical_url_construction():
    assert canonical_url_for("douyin", "123") == "https://www.douyin.com/video/123"
    assert (
        canonical_url_for("tiktok", "123", "bob")
        == "https://www.tiktok.com/@bob/video/123"
    )


def test_the_copy_link_short_form_is_recognised():
    # What the app's own "copy link" produces today. The older vm./vt.
    # forms still appear in pasted text, so all three must work.
    for url in (
        "https://www.tiktok.com/t/ZP83TmDmq/",
        "https://tiktok.com/t/ZP83TmDmq/",
        "https://vm.tiktok.com/ZMabc123/",
        "https://vt.tiktok.com/ZSabc123/",
    ):
        parsed = extract(url)
        assert parsed.platform == "tiktok", url
        assert parsed.needs_resolution is True, url
        assert parsed.video_id is None, url


def test_a_copy_link_inside_share_text_is_found():
    blob = "Check this out on TikTok https://www.tiktok.com/t/ZP83TmDmq/ 😍"
    parsed = extract(blob)
    assert parsed.platform == "tiktok"
    assert parsed.raw_url == "https://www.tiktok.com/t/ZP83TmDmq/"


def test_a_profile_url_is_not_taken_for_a_video():
    # Visiting an author's profile yields a URL with no video in it;
    # storing it as a video link would be wrong.
    parsed = extract("https://www.tiktok.com/@someuser")
    assert parsed.video_id is None


def test_the_forms_a_douyin_short_link_lands_on():
    """One run: 84 links followed, 84 landing pages we could not read.

    A v.douyin.com link does not land on www.douyin.com/video/ as often
    as the happy path suggests. These are the forms seen in the wild.
    """
    landings = {
        # What the app's own share link still redirects to.
        "https://www.iesdouyin.com/share/video/7123456789012345678/?region=CN": "7123456789012345678",
        # A 图文 post: an aweme id like any other, and in scope.
        "https://www.iesdouyin.com/share/note/7123456789012345679/": "7123456789012345679",
        "https://www.douyin.com/note/7123456789012345670": "7123456789012345670",
        # Opened over the author's page.
        "https://www.douyin.com/user/MS4wLjABAAAA?modal_id=7123456789012345671": "7123456789012345671",
        "https://www.douyin.com/video/7123456789012345672?x=1": "7123456789012345672",
    }
    for url, expected in landings.items():
        parsed = extract(url)
        assert parsed.platform == "douyin", url
        assert parsed.video_id == expected, url
        assert parsed.needs_resolution is False, url


def test_a_douyin_profile_is_still_not_a_video():
    parsed = extract("https://www.douyin.com/user/MS4wLjABAAAA")
    assert parsed.video_id is None


def test_the_share_text_names_the_author_and_quotes_the_caption():
    """A link that never paired to a capture is not an empty row.

    The dashboard showed dashes across every column for an unresolved
    link. The blob the share sheet produced was sitting in the same
    row all along.
    """
    from app.links import describe

    said = describe(
        "5.61 复制打开抖音，看看【我爱吃葡萄的作品】我出现的意义是想告诉你 "
        "你不再是一个人 # lwl... https://v.douyin.com/SXLSe2Qgzl4/ :8p"
    )
    assert said.author_name == "我爱吃葡萄"
    assert said.caption == "我出现的意义是想告诉你 你不再是一个人 # lwl..."


def test_share_text_that_says_nothing_yields_nothing():
    from app.links import describe

    said = describe("https://v.douyin.com/SXLSe2Qgzl4/")
    assert said.author_name is None
    assert said.caption is None


def test_the_handle_in_the_address_beats_the_one_off_the_screen(client, api_key):
    """A TikTok URL names its author; a screen reading is a stitch.

    The two have not been seen to disagree -- 25 links checked, all
    matching -- so this pins a precedence rather than a repair: the
    handle in the address is part of what resolves the video, and the
    screen reading is attached to the link by whatever the device
    parsed last.
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SharedLink

    response = client.post(
        "/api/links/shared",
        json={
            "raw_text": (
                "https://www.tiktok.com/@atlanticcoastpearl/video/7687820515369510629"
            ),
            "author_handle": "wasabide",  # what the screen said
            "shared_at": "2026-09-21T20:16:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200

    with SessionLocal() as session:
        link = session.scalars(select(SharedLink)).one()
        assert link.author_handle == "atlanticcoastpearl"


def test_a_douyin_link_still_takes_the_handle_the_device_read(client, api_key):
    """Douyin addresses carry no handle, so nothing competes there.

    The 抖音号 is read off the profile page and is the only source.
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SharedLink

    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.douyin.com/video/7688128736507805041",
            "author_handle": "70056222078",
            "shared_at": "2026-09-21T20:16:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    with SessionLocal() as session:
        assert session.scalars(select(SharedLink)).one().author_handle == "70056222078"
