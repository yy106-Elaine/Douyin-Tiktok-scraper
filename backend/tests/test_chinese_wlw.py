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


def test_a_kana_decorating_a_latin_hashtag_is_not_japanese():
    """`#fypシ` is a worldwide TikTok flourish, not a language.

    The kana rule was written for Japanese yuri, where 百合 matches the
    topic term perfectly. One katakana glued to the end of `fyp`
    excluded an English caption tagged `#rednote #chinesetimeofmylife`
    as Japanese -- a Chinese-diaspora row, thrown out for a decoration.
    """
    assert out("lmk if it's just me #wlw #twitter #rednote #chinesetimeofmylife #fypシ") is None


def test_real_japanese_is_still_japanese():
    """Kana standing on its own, which is what the rule was for."""
    assert classify(
        "中国人レズビアンのツイートが最強すぎて #wlw #おすすめ #レズビアン",
        policy=POLICY,
    ) == "japanese"
    assert classify("百合ヶ浜 かわいい", policy=POLICY) == "japanese"


def test_gl_on_tiktok_is_a_wlw_tag_not_a_genre():
    """A real couple's translated vlog is not scripted drama.

    `#shaorehushuo #wlw #gl #couple #chinese` is posted by the couple
    in it. The same account's posts were landing in the fiction
    stratum or not depending on whether `#gl` happened to be in the
    caption -- and that stratum is what separates "no author to
    interview" from "an author to interview".
    """
    assert out("#shaorehushuo #wlw #gl #couple #chinese") is None
    assert out("ignoring me 🙄 #wlw #china #gl #китай") is None
    assert out("Solo quiero ser una de ellas #girlslove #wlw #chinese #parati") is None


def test_gl_beside_a_genre_word_is_still_fiction_elsewhere():
    """On Douyin and YouTube it sits beside 短剧 and means the genre."""
    assert classify("百合短剧 #gl 双女主", policy="full") == "fiction"
    assert classify("女同短剧 第3集 双女主", policy="full") == "fiction"


def test_the_word_for_chinese_in_another_language_counts():
    """`pauta da semana: lésbicas chinesas` is the study's subject.

    The search reaches Portuguese, Spanish and French speakers talking
    about exactly this population, and an English-only spelling list
    threw them out as having nothing Chinese in them.
    """
    assert out("pauta da semana: lésbicas chinesas") is None
    assert out("lesbianas chinas") is None


def test_a_caption_the_app_cut_off_does_not_hide_a_hand_copied_row(client, api_key):
    """"re uploadd ...more" is not evidence that a video is off topic.

    A person chose this row one video at a time; the interface then
    truncated the caption mid-sentence. The carve-out in SQL had
    always covered it, and the Python pass over merged rows had not
    -- invisible while every TikTok caption passed anyway.
    """
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [{
                "platform_package": "com.zhiliaoapp.musically",
                "fingerprint": "tt::someuser::cut",
                "captured_at": "2026-09-14T12:00:00Z",
                "payload": {"author_handle": "someuser", "caption": "re uploadd ...more"},
            }],
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@someuser/video/7301234567890123456",
            "shared_at": "2026-09-14T12:00:30Z",
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "re uploadd" in body


def test_a_complete_caption_that_fails_the_rule_is_still_excluded(client, api_key):
    """The carve-out is for text that says nothing, not text that says no.

    A complete caption is the evidence the rule was written to read.
    Extending the carve-out to cover it would have quietly undone
    both this rule and Douyin's tag rule, since those rows carry ids
    too.
    """
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@elsewhere/video/7301111111111111111",
            "shared_at": "2026-09-14T18:00:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [{
                "platform_package": "com.zhiliaoapp.musically",
                "fingerprint": "tt::elsewhere::full",
                "captured_at": "2026-09-14T18:00:00Z",
                "payload": {
                    "author_handle": "elsewhere",
                    "caption": "opposites attract #wlw #wlwcouple",
                },
            }],
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "opposites attract" not in body


def test_remark_judges_a_row_on_the_page_caption_not_the_screen_one(client, api_key):
    """The stored verdict and the displayed one have to be the same.

    The phone reads what the interface rendered, and the interface
    truncates. `remark` was marking a row off topic on the half of
    its caption that fitted the screen, while the dashboard -- which
    already preferred the page's text -- showed it in scope. The CSV
    export reads the stored column, so the two disagreed about what
    the corpus was.
    """
    from app.db import SessionLocal
    from app.models import TikTokPost, WebVideo
    from app.relevance import remark

    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [{
                "platform_package": "com.zhiliaoapp.musically",
                "fingerprint": "tt::someuser::truncated",
                "captured_at": "2026-09-14T12:00:00Z",
                "payload": {
                    "author_handle": "someuser",
                    "caption": "our anniversary trip ...more",
                    "video_id_hint": "7301234567890123456",
                },
            }],
        },
        headers={"X-API-Key": api_key},
    )
    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.relevance == NO_CHINESE_MARK, post.relevance
        session.add(WebVideo(
            platform="tiktok",
            video_id="7301234567890123456",
            caption="our anniversary trip #chinese #wlw #lesbiancouple",
        ))
        session.commit()
        remark(session)
        assert session.query(TikTokPost).one().relevance is None
