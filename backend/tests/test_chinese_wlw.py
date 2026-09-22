"""TikTok: the search names the population, the results do not obey it."""

from app.relevance import (
    NO_CHINESE_MARK,
    NO_WLW_MARK,
    classify,
)

POLICY = "chinese-wlw"


def out(text: str) -> str | None:
    return classify(text, policy=POLICY)


def test_both_halves_present_is_in_scope():
    assert out("#Chinesecouple #Chineselesbian #wlw #fyp") is None
    assert out("I love Chinese lesbians.") is None
    assert out("nobody loves women more than these chinese lesbians #fyp") is None
    assert out("like it's a totally normal Monday for them#wlw #chinese") is None


def test_a_chinese_caption_needs_no_english_marker():
    """The characters are the Chinese element."""
    assert out("中国女同 日常 #wlw") is None
    assert out("我和女朋友的一天 #拉拉") is None


def test_lesbian_content_with_nothing_chinese_is_a_different_population():
    """Real video, wrong study.

    `Chinese lesbian` returns these; a rate computed over whatever
    else the recommender attached to the query is a rate for
    something other than Chinese WLW content.
    """
    assert out("#butchfemme #femme4butch #lesbiansoftiktok #highfemme") == NO_CHINESE_MARK
    assert out("wlw comforting gf crying scene") == NO_CHINESE_MARK
    assert out("#femmelesbian #wlw #fyp") == NO_CHINESE_MARK


def test_chinese_content_that_is_not_wlw_is_out_too():
    assert out("Chinese food is great #fyp") == NO_WLW_MARK
    assert out("中国旅游 vlog") == NO_WLW_MARK


def test_asian_alone_does_not_stand_in_for_chinese():
    """It names a population several times larger.

    Admitting it would restore the drift this rule exists to stop.
    """
    assert out("#asianlesbian #wlw") == NO_CHINESE_MARK


def test_queer_alone_does_not_stand_in_for_wlw():
    """lgbt and queer cover neighbouring populations, not this one."""
    assert out("chinese #lgbt #queer") == NO_WLW_MARK
    assert out("chinese #lgbt #lesbian") is None


def test_japanese_is_still_excluded_before_either_mark():
    """Kana is a hard rule; 百合 is the Japanese word for the genre."""
    assert out("百合ヶ浜 かわいい") not in (None, NO_CHINESE_MARK, NO_WLW_MARK)


def test_an_empty_caption_is_reported_as_empty_not_as_unchinese():
    assert out("") == "no text"
