"""Deciding what is in the corpus.

Chinese keyword search returns the search term's substrings, so these
tests are mostly a list of real collisions seen in collected data:
女同桌 for 女同, 拉拉裤 for 拉拉. Each one is a video that would
otherwise be counted as community content.
"""
import pytest

from app.relevance import HIDDEN, classify


@pytest.mark.parametrize(
    "text, reason",
    [
        # Real captions from a collection run.
        ("相亲遇高中女同桌，她坏笑给我夹菜", "not about the topic"),
        ("84年我交不起學費，是有錢的女同桌幫了我", "not about the topic"),
        ("女同学帮我补习数学", "not about the topic"),
        ("我的女同事天天迟到", "not about the topic"),
        ("成人拉拉裤 护理用品 老人失禁", "unrelated product"),
        ("货拉拉搬家多少钱", "unrelated product"),
        # 全集 makes this fiction, which is checked before the brand
        # collision; either answer excludes it.
        ("巴拉拉小魔仙全集", "fiction"),
        ("拉拉队舞蹈教学", "unrelated product"),
        ("100%純陀港女，精通穴位按摩 速預約: t.me/BabyM666", "advertising"),
        ("AI虚拟女同志 AI生成美女", "ai generated"),
        ("Lesbian couple reacts to their wedding video", "not in chinese"),
        ("ENTRE DOS HOMBRES GAY O DOS MUJERES", "not in chinese"),
        ("紫微斗數 課堂節錄 例子盤提供 女同志", "divination"),
        ("八字命理入门 女同志学员案例", "divination"),
        ("西芹百合炒虾仁做法", "no topic term"),
        ("百合莲子银耳汤 润肺止咳", "no topic term"),
        ("男同志情侣日常vlog", "no topic term"),
        ("同性恋婚姻合法化进程", "no topic term"),
        ("今天天气不错，出去走走", "no topic term"),
    ],
)
def test_known_collisions_are_named(text, reason):
    assert classify(text) == reason


@pytest.mark.parametrize(
    "text",
    [
        "女同性恋情侣日常vlog",
        "我是拉拉，出柜五年了",
        "女同志社群活动记录",
        "蕾丝边的自我认同",
        "同性恋女孩的出柜故事",
        "我和女朋友的日常 我们是拉拉",
        "我很宠我女朋友，我们是拉拉",
    ],
)
def test_community_content_is_in_scope(text):
    assert classify(text) is None


@pytest.mark.parametrize(
    "text",
    [
        # Short dramas, the largest single category in a real run.
        "百合短剧《错位红妆》ep 2 #古风 #百合 #治愈女同#女女恋",
        "【百合】失业遇失忆富家女，被她死死纠缠 | 治愈女同 GL",
        "甜宠短剧",
        "宠文推荐",
        "女同小说推荐 完结",
        "百合广播剧 第3集",
    ],
)
def test_fiction_is_excluded_even_carrying_a_topic_term(text):
    """Fiction has no author to interview about their own removal.

    This is the largest category by far, and it is a hard exclusion for
    that reason rather than because the text is off topic: 百合短剧 is
    on topic and still useless to a study that follows up with the
    people who posted.
    """
    assert classify(text) == "fiction"


@pytest.mark.parametrize(
    "text",
    [
        "拉拉公主NPC 攻略",
        "拉拉管玩具开箱",
        "和拉拉来到自在小院",
        "和拉拉聊了一下 地球村保安队长",
    ],
)
def test_games_and_toys_are_excluded(text):
    """Where 拉拉 turns up as a character or a brand."""
    assert classify(text) == "games and toys"


def test_a_topic_term_overrides_an_incidental_collision():
    """"女同学" beside a self-identification is a video about being 拉拉."""
    assert classify("我和女同学一起复习，顺便聊了聊我们是拉拉这件事") is None


def test_an_ambiguous_term_alone_is_not_enough():
    """The cost of the two-signal rule, stated as a test.

    These are real titles. 拉拉 and 女同 are fragments of too many
    ordinary words to be trusted alone, so a genuinely relevant video
    whose text carries nothing else is excluded. That is a recall loss
    accepted for precision, and it is visible under ?show=all.
    """
    for text in (
        "池上長虹拉拉車 2026/9/14",
        "拉拉山景區24顆神木全逛一遍",
        "拉拉秧 花椒",
        "傲拉拉 迦厄司 我好喜歡我自己",
        "父女同框有多甜 父女情深意濃",
        "母女同囚一座监狱",
        "港女同內地女生有咩分別？",
    ):
        assert classify(text) is not None, text


@pytest.mark.parametrize(
    "text",
    [
        "百合ヶ浜レベチ",
        "【百合アニメ #同時視聴】RELEASE THE SPYCE 1～6話",
        "百合の間に挟まる殺人鬼を許すな！",
        "百合ヶ丘駅に到着 #鉄道 #電車",
    ],
)
def test_japanese_yuri_content_is_excluded(text):
    """The bug that put a hundred Japanese videos in scope.

    百合 is the Japanese word for the same genre, and Japanese shares
    the CJK ideographs, so a "contains Chinese characters" test passed
    every one of them. Kana is what separates the languages.
    """
    assert classify(text) == "japanese"


def test_the_search_term_does_not_override_its_own_collision():
    """The bug this guards: 拉拉 inside 拉拉裤 counted as a topic term.

    Listed bare in the strong-term pattern, 拉拉 matched inside 拉拉裤
    and then overrode the exclusion written to catch it, so every
    packet of adult nappies stayed in the corpus.
    """
    assert classify("成人拉拉裤") == "unrelated product"
    assert classify("女同桌") == "not about the topic"


def test_advertising_outranks_a_topic_term():
    """Bait uses the keywords, so the topic term cannot clear it."""
    assert classify("女同性恋 上门服务 加微信 xxx") == "advertising"


def test_the_requirement_is_inclusion_not_absence_of_noise():
    """Chinese-language AND on topic. Anything else is out of scope.

    Every reason hides the row, so the burden is on the text to
    qualify rather than on a rule list to catch each way it can fail.
    Hidden is not deleted: `?show=all` lists them, and app/views.py
    keeps hand-collected phone rows visible whatever the text says.
    """
    for reason in (
        "advertising",
        "ai generated",
        "divination",
        "unrelated product",
        "not about the topic",
        "not in chinese",
        "no topic term",
        "no text",
    ):
        assert reason in HIDDEN, reason


def test_empty_text_is_recorded_not_guessed():
    assert classify(None, None) == "no text"
    assert classify("   ") == "no text"


class TestRemarking:
    """Re-reading the corpus after the rules change."""

    def _collect(self, session, title):
        from app import youtube

        def caller(endpoint, params):
            if endpoint == "search":
                return {"items": [{"id": {"videoId": "v1"}}]}
            return {
                "items": [
                    {
                        "id": "v1",
                        "snippet": {
                            "channelId": "UC1",
                            "channelTitle": "c",
                            "title": title,
                            "description": "",
                            "publishedAt": "2026-09-16T08:30:00Z",
                        },
                        "statistics": {},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }

        return youtube.collect(session, ["拉拉"], caller=caller)

    def test_collection_marks_a_row_as_it_arrives(self, client):
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import YouTubePost

        with SessionLocal() as session:
            self._collect(session, "成人拉拉裤 护理用品")
            post = session.scalars(select(YouTubePost)).one()
            assert post.relevance == "unrelated product"

    def test_remarking_is_idempotent_and_reports_the_tally(self, client):
        from app.db import SessionLocal
        from app.relevance import remark

        with SessionLocal() as session:
            self._collect(session, "货拉拉搬家")
            first = remark(session)
            assert first["changed"] == 0          # already marked on arrival
            assert first["unrelated product"] == 1
            assert remark(session)["changed"] == 0

    def test_a_corrected_rule_reaches_rows_already_collected(self, client, monkeypatch):
        """The reason the verbatim payload is kept.

        A rule list written from collisions someone noticed will be
        incomplete. Correcting it must not require collecting again --
        the videos may be gone by then.
        """
        import re

        from app.db import SessionLocal
        from app import relevance

        with SessionLocal() as session:
            self._collect(session, "我是拉拉，出柜了，分享一个新词 甲甲")
            assert remark_reason(session) is None

            # A collision discovered later.
            monkeypatch.setattr(
                relevance,
                "_HARD",
                relevance._HARD + (("unrelated product", re.compile("甲甲")),),
            )
            relevance.remark(session)
            assert remark_reason(session) == "unrelated product"


def remark_reason(session):
    from sqlalchemy import select

    from app.models import YouTubePost

    return session.scalars(select(YouTubePost)).one().relevance


class TestTheCarveOut:
    """Hand-collected phone rows stay visible whatever the text says."""

    def _capture(self, client, api_key, caption):
        return client.post(
            "/api/captures/batch",
            json={
                "device_id": "pixel-7a",
                "captures": [
                    {
                        "platform_package": "com.zhiliaoapp.musically",
                        "fingerprint": "tt::1",
                        "captured_at": "2026-09-14T12:00:00Z",
                        "payload": {"author_name": "someone", "caption": caption},
                    }
                ],
            },
            headers={"X-API-Key": api_key},
        )

    def test_a_truncated_caption_hides_a_phone_row_with_no_link(self, client, api_key):
        self._capture(client, api_key, "re uploadd ...more")
        body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
        assert "re uploadd" not in body

    def test_but_not_once_its_link_has_been_copied(self, client, api_key):
        """The rows that cost the most to collect are never hidden.

        A caption truncated to "...more" is no evidence about the
        video, and a person chose this one deliberately.
        """
        self._capture(client, api_key, "re uploadd ...more")
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

    def test_youtube_gets_no_such_exemption(self, client):
        """Every YouTube row has an id; the API chose them, not a person."""
        from app import youtube
        from app.db import SessionLocal

        def caller(endpoint, params):
            if endpoint == "search":
                return {"items": [{"id": {"videoId": "v1"}}]}
            return {
                "items": [
                    {
                        "id": "v1",
                        "snippet": {
                            "channelId": "UC1",
                            "channelTitle": "c",
                            "title": "货拉拉搬家报价",
                            "description": "",
                            "publishedAt": "2026-09-16T08:30:00Z",
                        },
                        "statistics": {},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }

        with SessionLocal() as session:
            youtube.collect(session, ["拉拉"], caller=caller)
        body = client.get("/dashboard?key=test-admin-key&platform=youtube").text
        assert "货拉拉" not in body
        assert "货拉拉" in client.get(
            "/dashboard?key=test-admin-key&platform=youtube&show=all"
        ).text


def test_the_keyword_breakdown_attributes_a_video_to_every_term(client):
    """Which term produced the noise, not just how much there was."""
    from app import youtube
    from app.db import SessionLocal
    from app.relevance import by_keyword

    def caller(endpoint, params):
        if endpoint == "search":
            return {"items": [{"id": {"videoId": "v1"}}]}
        return {
            "items": [
                {
                    "id": "v1",
                    "snippet": {
                        "channelId": "UC1",
                        "channelTitle": "c",
                        "title": "货拉拉搬家",
                        "description": "",
                        "publishedAt": "2026-09-16T08:30:00Z",
                    },
                    "statistics": {},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

    with SessionLocal() as session:
        youtube.collect(session, ["拉拉", "女同志"], caller=caller)
        table = by_keyword(session)
        # One video, found by both terms, counted against both.
        assert table["拉拉"] == {"unrelated product": 1}
        assert table["女同志"] == {"unrelated product": 1}


def test_the_parameter_breakdown_separates_runs_by_their_hint(client):
    """Whether relevanceLanguage helps is measurable, not assumable."""
    from app import youtube
    from app.db import SessionLocal
    from app.relevance import by_parameter

    def caller(video_id, title):
        def call(endpoint, params):
            if endpoint == "search":
                return {"items": [{"id": {"videoId": video_id}}]}
            return {
                "items": [
                    {
                        "id": video_id,
                        "snippet": {
                            "channelId": "UC1",
                            "channelTitle": "c",
                            "title": title,
                            "description": "",
                            "publishedAt": "2026-09-16T08:30:00Z",
                        },
                        "statistics": {},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }

        return call

    with SessionLocal() as session:
        youtube.collect(
            session, ["x"], caller=caller("v1", "Lesbian vlog"), relevance_language=""
        )
        youtube.collect(
            session,
            ["x"],
            caller=caller("v2", "拉拉情侣日常"),
            relevance_language="zh-Hans",
        )
        table = by_parameter(session)
        assert table["(none set)"] == {"not in chinese": 1}
        assert table["zh-Hans"] == {"in scope": 1}


class TestReviewingByCategory:
    """The dashboard has to let someone read what the filter removed."""

    def _collect(self, session, titles):
        from app import youtube

        def caller(endpoint, params):
            if endpoint == "search":
                return {"items": [{"id": {"videoId": f"v{i}"}} for i in range(len(titles))]}
            out = []
            for video_id in params["id"].split(","):
                index = int(video_id[1:])
                out.append(
                    {
                        "id": video_id,
                        "snippet": {
                            "channelId": f"UC{index}",
                            "channelTitle": "c",
                            "title": titles[index],
                            "description": "",
                            "publishedAt": "2026-09-16T08:30:00Z",
                        },
                        "statistics": {},
                        "status": {"privacyStatus": "public"},
                    }
                )
            return {"items": out}

        return youtube.collect(session, ["拉拉"], caller=caller)

    TITLES = [
        "我是拉拉，出柜五年了",          # in scope
        "百合短剧 第2集",                 # fiction
        "拉拉管玩具开箱",                 # games and toys
        "货拉拉搬家",                     # unrelated product
    ]

    def _body(self, client, show=""):
        query = f"&show={show}" if show else ""
        return client.get(
            f"/dashboard?key=test-admin-key&platform=youtube{query}"
        ).text

    def test_by_default_only_the_rows_in_scope_are_listed(self, client):
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client)
        assert "出柜五年" in body
        for off_topic in ("百合短剧", "玩具开箱", "货拉拉"):
            assert off_topic not in body

    def test_one_category_can_be_read_on_its_own(self, client):
        """Reading 500 mixed rows is not reading."""
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client, "fiction")
        assert "百合短剧" in body
        assert "玩具开箱" not in body
        assert "出柜五年" not in body

    def test_excluded_lists_every_hidden_row_and_no_others(self, client):
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client, "excluded")
        for off_topic in ("百合短剧", "玩具开箱", "货拉拉"):
            assert off_topic in body
        assert "出柜五年" not in body

    def test_each_category_is_offered_with_its_count(self, client):
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client)
        assert "show=fiction" in body
        assert "show=games+and+toys" in body or "show=games and toys" in body
        assert "excluded 3" in body


class TestTheExport:
    """What analysis reads should be the corpus, not everything seen."""

    def _collect(self, session):
        from app import youtube

        titles = ["我是拉拉，出柜五年了", "池上長虹拉拉車", "百合ヶ浜"]

        def caller(endpoint, params):
            if endpoint == "search":
                return {"items": [{"id": {"videoId": f"v{i}"}} for i in range(3)]}
            out = []
            for video_id in params["id"].split(","):
                index = int(video_id[1:])
                out.append(
                    {
                        "id": video_id,
                        "snippet": {
                            "channelId": f"UC{index}",
                            "channelTitle": "c",
                            "title": titles[index],
                            "description": "",
                            "publishedAt": "2026-09-16T08:30:00Z",
                        },
                        "statistics": {},
                        "status": {"privacyStatus": "public"},
                    }
                )
            return {"items": out}

        youtube.collect(session, ["拉拉"], caller=caller)

    def test_the_csv_carries_only_the_rows_in_scope(self, client):
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session)
        csv = client.get(
            "/api/export/posts.csv?platform=youtube",
            headers={"X-API-Key": "test-admin-key"},
        ).text
        assert "出柜五年" in csv
        assert "拉拉車" not in csv
        assert "百合ヶ浜" not in csv

    def test_everything_collected_is_still_exportable(self, client):
        """Excluded from a deliverable is not the same as deleted."""
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session)
        csv = client.get(
            "/api/export/posts.csv?platform=youtube&show=all",
            headers={"X-API-Key": "test-admin-key"},
        ).text
        for title in ("出柜五年", "拉拉車", "百合ヶ浜"):
            assert title in csv
