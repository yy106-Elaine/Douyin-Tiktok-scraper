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
