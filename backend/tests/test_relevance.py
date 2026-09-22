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
        # 巴拉拉 is the brand collision; 小魔仙 would also make it
        # children's media. Either answer excludes it.
        ("巴拉拉小魔仙全集", "unrelated product"),
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
        "🌈百合短剧Fall for You Again EP12",
        "【百合】遭匪掳走 治愈女同 Girlslove lesbian GL",
        "这是我画的百合漫画潮夏",
    ],
)
def test_fiction_is_in_the_corpus_but_labelled(text):
    """WLW fiction is WLW content, and its removal is the same event.

    It was excluded for a while on the argument that fiction has no
    author to interview. That argument bears on the interview half of
    the study, not on what counts as a takedown, so the corpus is the
    wrong place to enforce it. The label stays so an analysis that
    needs real accounts can filter on it.
    """
    from app.relevance import HIDDEN

    assert classify(text) == "fiction"
    assert "fiction" not in HIDDEN


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

    These are real titles. 拉拉 is the one keyword too polluted to
    count alone -- its collisions are names and places with no clean
    edge to key on -- so a genuinely relevant video carrying only 拉拉
    is excluded. That is a recall loss accepted for precision, and it
    is visible under ?show=all. 女同 and 百合 no longer pay this price:
    the words they hide inside are named, and their bulk polluters
    (Japanese yuri, fiction, lilies) have rules of their own.
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

    def test_an_excluded_caption_hides_a_phone_row_with_no_link(self, client, api_key):
        """A collision the search returned, with no link to vouch for it.

        This used to use an English caption, back when English alone
        was enough to hide a TikTok row. It is not any more -- see
        TestTikTokTrustsTheSearchTerm -- so the exclusion under test
        here is a keyword collision, which still stands.
        """
        self._capture(client, api_key, "货拉拉搬家电话，便宜")
        body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
        assert "货拉拉搬家" not in body

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
        "谷中百合花 钢琴演奏",            # no topic term
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
        for off_topic in ("百合花", "玩具开箱", "货拉拉"):
            assert off_topic not in body

    def test_one_category_can_be_read_on_its_own(self, client):
        """Reading 500 mixed rows is not reading."""
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client, "games and toys")
        assert "玩具开箱" in body
        assert "货拉拉" not in body
        assert "出柜五年" not in body

    def test_excluded_lists_every_hidden_row_and_no_others(self, client):
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client, "excluded")
        for off_topic in ("百合花", "玩具开箱", "货拉拉"):
            assert off_topic in body
        assert "出柜五年" not in body

    def test_each_category_is_offered_with_its_count(self, client):
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._collect(session, self.TITLES)
        body = self._body(client)
        assert "show=no+topic+term" in body or "show=no topic term" in body
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


def test_a_category_can_be_sampled_from_the_command_line(client):
    """Counts say how much a rule caught; captions say whether it was right."""
    from app import youtube
    from app.db import SessionLocal
    from app.relevance import sample

    titles = ["我们是拉拉，女朋友日常", "池上長虹拉拉車"]

    def caller(endpoint, params):
        if endpoint == "search":
            return {"items": [{"id": {"videoId": f"v{i}"}} for i in range(2)]}
        out = []
        for video_id in params["id"].split(","):
            index = int(video_id[1:])
            out.append(
                {
                    "id": video_id,
                    "snippet": {
                        "channelId": "UC1",
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

    with SessionLocal() as session:
        youtube.collect(session, ["拉拉"], caller=caller)
        assert [c for _, c in sample(session, "in scope")] == ["我们是拉拉，女朋友日常"]
        assert [c for _, c in sample(session, "no topic term")] == ["池上長虹拉拉車"]


class TestCorpusCounting:
    """What the dashboard reports as the corpus."""

    def _collect(self, session, titles, when, offset=0):
        from app import youtube

        def caller(endpoint, params):
            if endpoint == "search":
                return {
                    "items": [
                        {"id": {"videoId": f"v{offset + i}"}} for i in range(len(titles))
                    ]
                }
            out = []
            for video_id in params["id"].split(","):
                index = int(video_id[1:]) - offset
                out.append(
                    {
                        "id": video_id,
                        "snippet": {
                            "channelId": "UC1",
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

        youtube.collect(session, ["拉拉"], caller=caller, now=when)

    def test_the_corpus_counts_videos_not_rows(self, client):
        from datetime import datetime, timedelta

        from app.db import SessionLocal
        from app.views import unique_in_scope

        now = datetime(2026, 9, 18, 12, 0)
        with SessionLocal() as session:
            self._collect(session, ["我们是拉拉 女朋友日常", "百合ヶ浜"], now - timedelta(days=2))
            self._collect(session, ["女同情侣的日常 #les"], now - timedelta(days=1), 10)
            # An overlapping window re-finds the first two.
            self._collect(session, ["我们是拉拉 女朋友日常", "百合ヶ浜"], now)

            assert unique_in_scope(session, "youtube") == 2
            # Re-finding the first video today does not make it new.
            assert unique_in_scope(session, "youtube", now - timedelta(hours=6)) == 0
            assert unique_in_scope(session, "youtube", now - timedelta(days=3)) == 2

    def test_a_video_is_counted_on_the_day_it_first_arrived(self, client):
        """Otherwise an overlapping window turns a flat corpus into a rising one."""
        from datetime import datetime, timedelta

        from app.db import SessionLocal
        from app.views import daily_counts

        now = datetime(2026, 9, 18, 12, 0)
        with SessionLocal() as session:
            self._collect(session, ["我们是拉拉 女朋友日常"], now - timedelta(days=2))
            self._collect(session, ["女同情侣的日常 #les"], now, 10)
            self._collect(session, ["我们是拉拉 女朋友日常"], now)  # re-found, not new

            counts = dict(daily_counts(session, "youtube", days=3, now=now))
            assert counts["2026-09-16"] == 1
            assert counts["2026-09-17"] == 0
            assert counts["2026-09-18"] == 1

    def test_off_topic_videos_are_not_in_the_corpus_count(self, client):
        from datetime import datetime

        from app.db import SessionLocal
        from app.views import unique_in_scope

        now = datetime(2026, 9, 18, 12, 0)
        with SessionLocal() as session:
            self._collect(session, ["百合ヶ浜", "拉拉車", "南通花店 #百合花"], now)
            assert unique_in_scope(session, "youtube") == 0


def test_the_dashboard_styles_its_own_components(client):
    """Three CSS blocks were silently never inserted.

    Each was added with a str.replace whose anchor used doubled braces,
    left over from when the stylesheet lived inside an f-string. The
    anchors matched nothing, the replaces did nothing, and the page
    shipped with the review chips as a run-on line of links and the
    day strip as digits with no bars. Nothing failed; it just looked
    wrong on a screen I was not looking at.
    """
    body = client.get("/dashboard?key=test-admin-key&platform=youtube").text
    for rule in (".chip {", ".chips {", ".dbar {", ".dlabel {", "td.rank {"):
        assert rule in body, rule
    # And no literal doubled braces anywhere in the stylesheet.
    start = body.index("<style>")
    assert "{{" not in body[start : body.index("</style>", start)]


def test_rows_are_numbered(client):
    from app import youtube
    from app.db import SessionLocal

    def caller(endpoint, params):
        if endpoint == "search":
            return {"items": [{"id": {"videoId": f"v{i}"}} for i in range(2)]}
        return {
            "items": [
                {
                    "id": video_id,
                    "snippet": {
                        "channelId": "UC1",
                        "channelTitle": "c",
                        "title": "我们是拉拉 女朋友日常",
                        "description": "",
                        "publishedAt": "2026-09-16T08:30:00Z",
                    },
                    "statistics": {},
                    "status": {"privacyStatus": "public"},
                }
                for video_id in params["id"].split(",")
            ]
        }

    with SessionLocal() as session:
        youtube.collect(session, ["拉拉"], caller=caller)
    body = client.get("/dashboard?key=test-admin-key&platform=youtube").text
    assert '<td class="rank">1</td>' in body
    assert '<td class="rank">2</td>' in body


@pytest.mark.parametrize(
    "text",
    [
        # Adult nappies, from a channel posting them daily.
        "#卧床老人 #护理用品 #成人拉拉裤 #乐余年拉拉裤",
        # A children's cartoon whose title contains 拉拉, which reached
        # in through 动漫 as a companion.
        "第86集：巴拉拉小魔仙 #巴拉拉小魔仙 #我在抖音看动漫 #童年回忆",
    ],
)
def test_a_confirmed_guess_cannot_override_its_own_collision(text):
    """The third time this shape has bitten.

    A soft exclusion names a word the keyword hides inside, so letting
    an ambiguous term that a companion merely confirmed override it
    re-creates the original bug: 拉拉 overriding 拉拉裤. Only an
    unambiguous term (lesbian, 女同性恋, 出柜, 是拉拉) may override.
    """
    assert classify(text) == "unrelated product"


def test_an_unambiguous_term_still_overrides_a_collision():
    """"女同学" beside "我们是拉拉" is a video about being 拉拉."""
    assert classify("我和女同学一起复习，顺便聊了聊我们是拉拉这件事") is None


class TestPlatformsWithoutATopicFilter:
    """Douyin is sampled from community hashtags, so it is not filtered.

    The distinction is the sampling frame, not the language. A YouTube
    keyword search returns whatever the API matched and about 6% of it
    is in scope; #lwl is a tag the community puts on its own posts, so
    the search is already the filter.

    Measured, not assumed: the first Douyin run marked every row
    "no topic term" -- captions like 许愿这次别再丢下我#lwl, plainly on
    topic and saying so with a tag rather than a term. Filtering them
    hid the whole platform, and the video ids with it.
    """

    def _capture(self, client, api_key, caption):
        response = client.post(
            "/api/captures/batch",
            json={
                "device_id": "pixel-7a",
                "captures": [
                    {
                        "platform_package": "com.ss.android.ugc.aweme",
                        "fingerprint": f"douyin::someone::{caption}",
                        "captured_at": "2026-09-19T02:09:00Z",
                        "payload": {"author_name": "someone", "caption": caption},
                    }
                ],
            },
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

    def _douyin_relevance(self):
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import DouyinPost

        with SessionLocal() as session:
            return [p.relevance for p in session.scalars(select(DouyinPost))]

    def test_a_hashtag_only_caption_stays_in_scope(self, client, api_key):
        # Real captions from the first assisted run on the study phone.
        self._capture(client, api_key, "许愿这次别再丢下我#lwl#lwl")
        self._capture(client, api_key, "今夜的风悄悄月悄悄 吻你的眉梢#lwl #最帅")
        assert self._douyin_relevance() == [None, None]

    def test_remarking_does_not_reintroduce_an_exclusion(self, client, api_key):
        """Turning the filter off has to clear what it marked before.

        Otherwise the rows stay hidden and the switch looks broken.
        """
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import DouyinPost
        from app.relevance import remark

        self._capture(client, api_key, "许愿这次别再丢下我#lwl")
        with SessionLocal() as session:
            for post in session.scalars(select(DouyinPost)):
                post.relevance = "no topic term"
            session.commit()
            tally = remark(session)

        assert tally["changed"] == 1
        assert self._douyin_relevance() == [None]

    def test_youtube_is_still_filtered(self, client):
        """The point is a platform distinction, not removing the filter."""
        from app.db import SessionLocal
        from app.relevance import remark

        with SessionLocal() as session:
            TestRemarking()._collect(session, "货拉拉搬家公司电话")
            assert remark(session)["unrelated product"] == 1


class TestTikTokTrustsTheSearchTerm:
    """Searched by hand, and the search term names the population.

    This class used to assert the opposite -- that English was
    excluded -- on the assumption that a TikTok search behaves like a
    Douyin one. It does not. 女同性恋, 女同 and 拉拉 on the
    international build return every language at once and almost
    nothing from this study's population; the terms that work name it
    directly (`Chinese lesbian`, 中国女同), and what they surface is
    Chinese and diaspora creators captioning in English.

    So the language test goes. The collision rules do not: a delivery
    ad, a divination channel and Japanese yuri are still out.
    """

    def _tiktok(self, client, api_key, caption):
        response = client.post(
            "/api/captures/batch",
            json={
                "device_id": "pixel-7a",
                "captures": [
                    {
                        "platform_package": "com.zhiliaoapp.musically",
                        "fingerprint": f"tt::someone::{caption}",
                        "captured_at": "2026-09-19T02:09:00Z",
                        "payload": {"author_name": "someone", "caption": caption},
                    }
                ],
            },
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

    def _relevance(self):
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import TikTokPost

        with SessionLocal() as session:
            return [p.relevance for p in session.scalars(select(TikTokPost))]

    def test_chinese_with_no_topic_term_is_kept(self, client, api_key):
        """The change: this used to be excluded as "no topic term"."""
        self._tiktok(client, api_key, "许愿这次别再丢下我")
        assert self._relevance() == [None]

    def test_english_is_kept(self, client, api_key):
        """The change: this used to be excluded as "not in chinese"."""
        self._tiktok(client, api_key, "my girlfriend and i wlw couple")
        assert self._relevance() == [None]

    def test_english_with_no_topic_term_is_kept_too(self, client, api_key):
        """A caption the search chose, saying nothing about itself.

        Neither test the other platforms apply can be met by this
        text, and on TikTok neither is asked of it.
        """
        self._tiktok(client, api_key, "three years together and counting")
        assert self._relevance() == [None]

    def test_japanese_is_still_excluded(self, client, api_key):
        self._tiktok(client, api_key, "百合カップルの日常です")
        assert self._relevance() == ["japanese"]

    def test_a_keyword_collision_is_still_excluded(self, client, api_key):
        """Looser is not "off". A 货拉拉 delivery ad is not made relevant
        by having been returned for a search for 拉拉."""
        self._tiktok(client, api_key, "货拉拉搬家电话，便宜")
        assert self._relevance() == ["unrelated product"]


def test_the_policy_for_an_unknown_platform_is_the_strictest_one():
    """A new platform must not silently collect everything."""
    from app.platforms import filter_policy

    assert filter_policy("some_new_app") == "full"
    assert filter_policy(None) == "full"


class TestDouyinWantsTheTagWritten:
    """`#lwl` is a label the poster attached. `lwl` is a string.

    Douyin ran no topic filter at all, on the argument that the
    community hashtags are the filter. That argument survives; this
    is it taken one step further. The bare token turns up as an
    account name and inside unrelated titles, and every one of these
    captions was in the corpus.
    """

    def _out(self, caption: str) -> str | None:
        from app.relevance import classify

        return classify(caption, policy="tags")

    def test_the_token_alone_is_not_the_topic(self):
        from app.relevance import UNTAGGED

        for caption in (
            "LWL出游随拍记录",
            "LWL回顾经典，百听不厌",
            "威龙LWL6666668888",
        ):
            assert self._out(caption) == UNTAGGED, caption

    def test_written_as_a_tag_it_is(self):
        for caption in (
            "许愿这次别再丢下我#lwl#lwl",
            "今夜的风悄悄月悄悄 吻你的眉梢#lwl",
            "如果我想让你只属于我，你会不会觉得我太自私 #lwl #萌t",
            "再来一次 我不会再与你相恋#wlw",
            "维持现状就很好呢 说清楚就不可爱了#lwl",
        ):
            assert self._out(caption) is None, caption

    def test_a_caption_about_the_topic_keeps_the_row(self):
        """LWL第一次追女孩子到手了 is an account named LWL, writing
        about pursuing a girl. The tag rule must not take it."""
        assert self._out("LWL第一次追女孩子到手了") is None
        assert self._out("LWL 和女朋友的日常") is None

    def test_a_caption_with_no_token_is_untouched(self):
        """Nothing else runs on this platform: no language test, no
        topic term required. The search is still the filter."""
        assert self._out("早安各位小主，挤公交上班") is None
        assert self._out("我和女朋友的日常") is None
        assert self._out("") == "no text"

    def test_the_boundary_is_not_a_word_boundary(self):
        """`\\blwl\\b` matched none of these.

        Python counts CJK as word characters, so there is no boundary
        between `LWL` and `出` -- and the rule silently did nothing to
        every caption it was written for.
        """
        import re

        from app.relevance import LOOSE_TAG

        assert not re.search(r"\blwl\b", "LWL出游随拍记录", re.IGNORECASE)
        assert LOOSE_TAG.search("LWL出游随拍记录")
        assert LOOSE_TAG.search("威龙LWL6666668888")
        # Still not a substring of an ordinary word.
        assert not LOOSE_TAG.search("lesbian")
