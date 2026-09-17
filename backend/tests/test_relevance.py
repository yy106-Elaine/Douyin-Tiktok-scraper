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
        ("巴拉拉小魔仙全集", "unrelated product"),
        ("拉拉队舞蹈教学", "unrelated product"),
        ("100%純陀港女，精通穴位按摩 速預約: t.me/BabyM666", "advertising"),
        ("AI虚拟女同志 AI生成美女", "ai generated"),
        ("Lesbian couple reacts to their wedding video", "not in chinese"),
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
        "百合短剧《错位红妆》#百合 #治愈女同#女女恋",
        "女同志社群活动记录",
        "蕾丝边的自我认同",
    ],
)
def test_community_content_is_in_scope(text):
    assert classify(text) is None


def test_a_topic_term_overrides_an_incidental_collision():
    """"女同学" beside "拉拉" is a video about being a 拉拉."""
    assert classify("我和女同学一起复习，顺便聊了聊我们是拉拉这件事") is None


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


def test_only_positive_evidence_hides_a_row():
    """Absence of a keyword is not evidence the video is off topic.

    Phone captures often render a truncated caption or none at all,
    and English-hashtag posts are the community content under study.
    """
    assert "no topic term" not in HIDDEN
    assert "not in chinese" not in HIDDEN
    assert "no text" not in HIDDEN
    assert "advertising" in HIDDEN
    assert "unrelated product" in HIDDEN


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
            self._collect(session, "我是拉拉，分享一个新词 甲甲")
            assert remark_reason(session) is None

            # A collision discovered later.
            monkeypatch.setattr(
                relevance,
                "_SOFT",
                relevance._SOFT + (("unrelated product", re.compile("甲甲")),),
            )
            monkeypatch.setattr(relevance, "STRONG", re.compile("女同性恋"))
            relevance.remark(session)
            assert remark_reason(session) == "unrelated product"


def remark_reason(session):
    from sqlalchemy import select

    from app.models import YouTubePost

    return session.scalars(select(YouTubePost)).one().relevance
