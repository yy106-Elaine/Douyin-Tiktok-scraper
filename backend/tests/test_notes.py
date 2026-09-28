"""图文 posts: image-and-text, the format the tag searches actually return.

On 2026-09-28 a phone search for `lwl` came back full -- posted four
hours ago, eleven hours ago, over a thousand likes -- and none of it
was video. A study that collects only video had been reading that as
an empty tag for four days.
"""
from pathlib import Path

import pytest

from app.daily import one
from app.douyin_page import NOTE_URL, image_urls
from app.download_videos import held, image_kind, save_image
from app.fetch_videos import SITES
from app.platforms import filter_policy
from app.recheck import BROWSER_ONLY

@pytest.fixture()
def session(db):
    from app.db import SessionLocal

    with SessionLocal() as open_session:
        yield open_session


JPEG = b"\xff\xd8\xff" + b"x" * 5_000
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 5_000


def _note(video_id: str, caption: str, images: int = 2) -> dict:
    return {
        "aweme_detail": {
            "aweme_id": video_id,
            "desc": caption,
            "author": {"nickname": "酸奶烧烧", "unique_id": "sour"},
            "statistics": {"digg_count": 1401},
            "images": [
                {"url_list": [f"https://a/{n}.jpg", f"https://mirror/{n}.jpg"]}
                for n in range(1, images + 1)
            ],
        }
    }


class TestAddresses:
    def test_a_note_is_not_served_from_the_video_path(self):
        assert "/note/" in NOTE_URL
        assert SITES["douyin_note"].page_url("7689", None).endswith("/note/7689")

    def test_the_mirrors_of_one_picture_stay_together(self):
        """Two levels, and they mean different things.

        Across the list: different pictures, all wanted. Within one:
        mirrors of the same picture, one of which is enough. Flattened,
        a two-image post would download four files and call itself
        complete after the first two.
        """
        groups = image_urls(payloads=[_note("7689", "x", images=2)], video_id="7689")
        assert len(groups) == 2
        assert groups[0] == ["https://a/1.jpg", "https://mirror/1.jpg"]

    def test_images_filed_under_another_post_s_id_are_refused(self):
        """Douyin answers a removed post by serving a different one.

        Images kept under the wrong id are worse than no images: the
        folder looks complete and the corpus is wrong where nobody
        will look.
        """
        assert image_urls(payloads=[_note("7689", "x")], video_id="9999") == []


class TestPolicy:
    def test_a_note_is_judged_by_the_same_rule_as_a_video(self):
        assert filter_policy("douyin_note") == "tags"

    def test_an_unknown_douyin_variant_still_gets_the_strictest_policy(self):
        assert filter_policy("douyin_reels") == "full"

    def test_an_anonymous_request_cannot_read_a_note_either(self):
        assert "douyin_note" in BROWSER_ONLY


class TestArchive:
    def test_an_error_page_is_not_an_image(self):
        assert image_kind(b"<html>not signed in</html>") is None
        assert image_kind(JPEG) == ".jpg"
        assert image_kind(PNG) == ".png"

    def test_a_small_card_is_still_an_image(self):
        """The video floor is 50 KB. A 图文 card is often less.

        Measuring an image by a video's size threw away real posts;
        the signature in the first bytes is the stronger test anyway.
        """
        assert image_kind(b"\xff\xd8\xff" + b"x" * 1_500) == ".jpg"

    def test_the_post_s_order_survives_on_disk(self, tmp_path):
        """A chat log split across four cards reads as nonsense shuffled."""
        first = save_image(tmp_path, "7689", 1, JPEG)
        tenth = save_image(tmp_path, "7689", 10, JPEG)
        assert first.name == "01.jpg"
        assert sorted(p.name for p in first.parent.iterdir()) == ["01.jpg", "10.jpg"]
        assert tenth.parent == first.parent


class TestAPass:
    """`one()` over a note, with the browser replaced by two functions."""

    def _page(self, video_id, caption, images=2):
        from app.pagedata import Fetched

        return Fetched(
            url=f"https://www.douyin.com/note/{video_id}",
            http_status=200,
            html="",
            payloads=[_note(video_id, caption, images)],
        )

    def test_every_picture_is_kept_and_the_row_names_the_folder(
        self, session, tmp_path
    ):
        asked = []

        def download(address, referer):
            asked.append(address)
            return JPEG, 200

        outcome, said, kept = one(
            session,
            read=lambda url: self._page("7689", "拉拉们都是怎么谈上的啊 #lwl #le", 3),
            download=download,
            video_id="7689",
            site=SITES["douyin_note"],
            handle=None,
            directory=tmp_path,
        )
        assert outcome == "saved"
        assert kept == 3 * len(JPEG)
        # One request per picture, not per mirror.
        assert len(asked) == 3
        assert sorted(p.name for p in (tmp_path / "7689").iterdir()) == [
            "01.jpg", "02.jpg", "03.jpg",
        ]

    def test_a_dead_mirror_falls_through_to_the_next(self, session, tmp_path):
        def download(address, referer):
            if address.startswith("https://a/"):
                return None, 403
            return JPEG, 200

        outcome, said, kept = one(
            session,
            read=lambda url: self._page("7689", "#lwl #le", 2),
            download=download,
            video_id="7689",
            site=SITES["douyin_note"],
            handle=None,
            directory=tmp_path,
        )
        assert outcome == "saved"
        assert len(list((tmp_path / "7689").iterdir())) == 2

    def test_a_post_missing_one_picture_is_not_recorded_as_held(
        self, session, tmp_path
    ):
        """Unlike a truncated video, an incomplete post looks fine.

        So it is recorded as an error and tried again next pass, while
        the post is still there to try.
        """
        def download(address, referer):
            if address.endswith("/2.jpg"):
                return b"<html>gone</html>", 200
            return JPEG, 200

        outcome, said, kept = one(
            session,
            read=lambda url: self._page("7689", "#lwl #le", 2),
            download=download,
            video_id="7689",
            site=SITES["douyin_note"],
            handle=None,
            directory=tmp_path,
        )
        assert outcome == "read"
        assert kept == 0
        assert "image 2/2" in said

    def test_an_off_topic_note_is_read_but_not_kept(self, session, tmp_path):
        """The page visit is the takedown check and happens either way."""
        asked = []
        outcome, said, kept = one(
            session,
            read=lambda url: self._page("7689", "今天吃什么 #美食"),
            download=lambda a, r: asked.append(a) or (JPEG, 200),
            video_id="7689",
            site=SITES["douyin_note"],
            handle=None,
            directory=tmp_path,
        )
        assert outcome == "read"
        assert asked == []
        assert "not kept" in said


class TestSnapshot:
    """A copy before the long pass, taken the way a live file must be."""

    def test_the_copy_opens(self, tmp_path, db):
        import sqlite3

        from app.db import snapshot

        kept = snapshot(tmp_path)
        assert kept is not None and kept.is_file()
        answer = sqlite3.connect(kept).execute("PRAGMA integrity_check").fetchone()
        assert answer[0] == "ok"

    def test_it_uses_sqlite_s_own_backup_not_a_file_copy(self, tmp_path, db):
        """A file copied mid-write is a copy that is mid-write.

        Which is the worst kind of backup: it exists, it is the right
        size, and it is unopenable in the one moment it is needed.
        """
        import sqlite3

        from app.db import SessionLocal, snapshot
        from app.models import LinkCheck

        with SessionLocal() as open_session:
            open_session.add(
                LinkCheck(
                    platform="douyin_note",
                    video_id="7689",
                    target_kind="video",
                    url="https://www.douyin.com/note/7689",
                    http_status=200,
                    checked_at=__import__("datetime").datetime(2026, 9, 28, 2, 0),
                )
            )
            open_session.commit()
            # Copy taken with a session still open on the source.
            kept = snapshot(tmp_path)

        rows = sqlite3.connect(kept).execute(
            "select count(*) from link_checks"
        ).fetchone()[0]
        assert rows >= 1

    def test_old_copies_are_dropped_and_recent_ones_are_not(self, tmp_path, db):
        from app.db import snapshot

        for _ in range(4):
            snapshot(tmp_path, keep=2)
        assert len(list(tmp_path.glob("scraper-*.db"))) <= 2


class TestSharedLinks:
    """A 图文 link copied on the phone, with no app change at all."""

    def test_a_note_share_link_is_not_filed_as_a_video(self):
        from app.links import extract

        shared = (
            "5.61 复制打开抖音，看看【酸奶烧烧的作品】拉拉们都是怎么谈上的啊"
            "#拉子们 #lwl #le https://www.iesdouyin.com/share/note/"
            "7689123456789012345/ :8p"
        )
        link = extract(shared)
        assert link.platform == "douyin_note"
        assert link.video_id == "7689123456789012345"
        assert link.canonical_url.endswith("/note/7689123456789012345")

    def test_a_video_link_is_still_a_video(self):
        from app.links import extract

        link = extract("https://www.douyin.com/video/7689123456789012345")
        assert link.platform == "douyin"
        assert "/video/" in link.canonical_url

    def test_a_modal_id_says_nothing_about_the_kind(self):
        """Opened over an author's page, the address carries no kind.

        Guessing "note" there would send video ids to /note/, which is
        the same mistake pointed the other way.
        """
        from app.links import extract

        link = extract("https://www.douyin.com/user/MS4wLj?modal_id=7689123456789012345")
        assert link.platform == "douyin"

    def test_the_share_text_still_gives_author_and_caption(self):
        """The caption is what the filter runs on, and it is in the text."""
        from app.links import describe

        said = describe(
            "5.61 复制打开抖音，看看【酸奶烧烧的作品】拉拉们都是怎么谈上的啊 "
            "#lwl #le https://www.iesdouyin.com/share/note/7689/ :8p"
        )
        assert said.author_name == "酸奶烧烧"
        assert "#lwl" in (said.caption or "")


class TestPasted:
    """Collection by hand, for the days the phone cannot reach anything."""

    def test_blocks_split_where_a_person_pastes(self):
        from app.paste import blocks

        assert blocks("a\n\nb\n\n\n c \n") == ["a", "b", "c"]
        assert blocks("   ") == []

    def test_a_pasted_note_becomes_the_row_the_phone_would_have_sent(
        self, session
    ):
        from app.paste import store

        row, said = store(
            session,
            "5.61 复制打开抖音，看看【酸奶烧烧的作品】拉拉们都是怎么谈上的啊 "
            "#lwl #le https://www.iesdouyin.com/share/note/7689123456789012345/",
            participant_id="P001",
        )
        assert row is not None
        assert row.platform == "douyin_note"
        assert row.video_id == "7689123456789012345"
        assert row.canonical_url.endswith("/note/7689123456789012345")
        # And it says it had no capture behind it.
        assert row.source == "pasted"

    def test_the_same_post_pasted_twice_is_not_two_sightings(self, session):
        from app.paste import store

        text = "【酸奶烧烧的作品】x https://www.douyin.com/note/7689123456789012345"
        first, _ = store(session, text, participant_id="P001")
        second, why = store(session, text, participant_id="P001")
        assert first is not None
        assert second is None
        assert "already known" in why

    def test_text_with_no_link_is_refused_rather_than_stored_empty(self, session):
        from app.paste import store

        row, why = store(session, "拉拉们都是怎么谈上的啊", participant_id="P001")
        assert row is None
        assert "no link" in why

    def test_a_short_link_is_stored_for_resolve_to_follow(self, session):
        """No id yet, and that is fine: app.resolve follows it later."""
        from app.paste import store

        row, _ = store(
            session,
            "7.88 【7iiu^的作品】每天和姐姐都好幸福呀 #lwl https://v.douyin.com/abcdefg/",
            participant_id="P001",
        )
        assert row is not None
        assert row.video_id is None
        assert row.raw_text


class TestShareSheetSaysWhich:
    """抖音's own share text names the kind, before any redirect.

    Which matters because nearly every link copied on a phone is a
    short one: without this the kind is unknown until `app.resolve`
    runs, and on a travel week that can be days.
    """

    def test_图文作品_is_a_note_even_as_a_short_link(self):
        from app.links import extract

        link = extract(
            "2.51 复制打开抖音，看看【嵐的图文作品】# wlw# 年上 "
            "https://v.douyin.com/nYrwjP_Cfs4/ c@N.Wm"
        )
        assert link.platform == "douyin_note"
        assert link.needs_resolution is True

    def test_作品_alone_is_a_video(self):
        from app.links import extract

        link = extract(
            "7.99 复制打开抖音，看看【悄悄的小八的作品】你的黑长直已上线# lwl "
            "https://v.douyin.com/5F3noRWBzcs/"
        )
        assert link.platform == "douyin"

    def test_the_author_survives_的图文作品(self):
        """The pattern wanted 的作品】 and 图文 sits between the two.

        So every 图文 row lost its author and its caption -- and the
        caption is what the filter runs on, so the row went out as
        untagged. Found the day the corpus became mostly 图文.
        """
        from app.links import describe

        said = describe(
            "4.84 复制打开抖音，看看【皓明的图文作品】好可爱的老婆...好喜欢"
            "# wlw# la# 恋爱... https://v.douyin.com/2mtISHhKpHc/"
        )
        assert said.author_name == "皓明"
        assert "# wlw" in said.caption

    def test_a_blob_with_no_author_still_yields_its_caption(self):
        """The other share form: caption first, no 【】 at all."""
        from app.links import describe

        said = describe(
            "9.94 淡淡的稳稳的幸福的两个人 # lwl # 同居日常 # 妻妻 "
            "https://v.douyin.com/2gei-utzpv4/ 复制此链接，打开抖音搜索，直接观看视频！"
        )
        assert said.author_name is None
        assert said.caption.startswith("淡淡的稳稳的幸福的两个人")
        assert "#" in said.caption

    def test_these_captions_are_in_scope(self):
        """The filter is unchanged; 图文 captions label themselves too."""
        from app.relevance import classify

        for caption in (
            "# wlw# 年上# 无名女士# 嵐",
            "一半一伴.# wlw",
            "淡淡的稳稳的幸福的两个人 # lwl # 同居日常 # 妻妻",
            "闺蜜我爱你# wlw # h # 朋友",
        ):
            assert classify(caption, policy="tags") is None, caption


class TestWhenItWasCollected:
    """The sighting happened when it happened, not when it was typed in."""

    def test_a_local_date_becomes_that_day_at_midday_utc(self):
        from app.paste import _when

        # America/New_York, so noon local is 16:00 UTC in September.
        assert _when("2026-09-27") == __import__("datetime").datetime(
            2026, 9, 27, 16, 0
        )

    def test_an_evening_crosses_into_the_next_utc_day(self):
        """22:10 in Boston is 02:10 tomorrow in UTC, and that is fine.

        What must not happen is the reverse: storing 22:10 as if it
        were UTC, which would date the sighting four hours early and,
        for an evening's work, a whole day late in every local bucket.
        """
        from app.paste import _when

        assert _when("2026-09-27 22:10") == __import__("datetime").datetime(
            2026, 9, 28, 2, 10
        )

    def test_a_time_it_cannot_read_stops_rather_than_guesses(self):
        import pytest as _pytest

        from app.paste import _when

        with _pytest.raises(SystemExit):
            _when("last tuesday")

    def test_the_row_carries_the_time_it_was_given(self, session):
        from datetime import datetime

        from app.paste import store

        row, _ = store(
            session,
            "【嵐的图文作品】# wlw https://www.douyin.com/note/7689123456789012345",
            participant_id="P001",
            shared_at=datetime(2026, 9, 27, 16, 0),
        )
        assert row.shared_at == datetime(2026, 9, 27, 16, 0)


class TestGoingBackForTheThinReads:
    """A page that gave up only its meta tags leaves a row and no file."""

    def test_the_selector_finds_exactly_those(self, session):
        from sqlalchemy import select

        from app.models import WebVideo

        for video_id, how in (
            ("1", "api"), ("2", "surface"), ("3", "embedded"), ("4", "surface"),
        ):
            session.add(
                WebVideo(platform="douyin_note", video_id=video_id, parsed_by=how)
            )
        session.commit()

        thin = {
            found
            for (found,) in session.execute(
                select(WebVideo.video_id).where(
                    WebVideo.platform == "douyin_note",
                    WebVideo.parsed_by == "surface",
                )
            )
        }
        assert thin == {"2", "4"}

    def test_a_download_that_failed_is_also_unarchived(self, session):
        """The other way a post ends up read and not kept.

        The page gave its addresses, the fetch of one image failed, and
        the row exists with a download_error. Nothing about that row is
        "surface", so a selector looking only at parsed_by walks past
        it -- which is how a post can sit read, unarchived and
        unretried until it disappears.
        """
        from sqlalchemy import or_, select

        from app.models import WebVideo

        session.add(
            WebVideo(platform="douyin_note", video_id="5", parsed_by="api",
                     download_error="image 1/1: Error")
        )
        session.add(
            WebVideo(platform="douyin_note", video_id="6", parsed_by="api",
                     local_path="/tmp/6")
        )
        session.commit()

        missed = {
            found
            for (found,) in session.execute(
                select(WebVideo.video_id).where(
                    WebVideo.platform == "douyin_note",
                    or_(
                        WebVideo.parsed_by == "surface",
                        WebVideo.download_error.isnot(None),
                    ),
                )
            )
        }
        assert "5" in missed
        assert "6" not in missed

    def test_new_only_would_never_come_back_for_them(self, session):
        """Which is why the flag exists.

        The row is there and carries no fetch error, so `wanted` counts
        the post as read. Without a way to name them, a post read from
        the surface is archived never -- and its images go when it does.
        """
        from app.fetch_videos import wanted
        from app.models import SharedLink, WebVideo
        from app.clock import now as utc_now

        session.add(
            SharedLink(
                participant_id="P001",
                platform="douyin_note",
                raw_text="x",
                video_id="7689",
                canonical_url="https://www.douyin.com/note/7689",
                shared_at=utc_now(),
            )
        )
        session.add(
            WebVideo(platform="douyin_note", video_id="7689", parsed_by="surface")
        )
        session.commit()

        assert wanted(session, "douyin_note", refresh=False) == []
        assert wanted(session, "douyin_note", refresh=True) == ["7689"]


class TestOnePlatformAtATime:
    """For a network that reaches one site and not the other."""

    def _targets(self):
        from app.recheck import Target

        from datetime import datetime

        seen = datetime(2026, 9, 20, 12, 0)
        return [
            Target("youtube", "a", "https://y/a", None, seen),
            Target("tiktok", "b", "https://t/b", None, seen),
            Target("youtube", "c", "https://y/c", None, seen),
        ]

    def test_only_the_named_platform_is_checked(self, db):
        from app.db import SessionLocal
        from app.recheck import FetchResult
        from app.recheck import run_round

        asked = []

        def fetcher(url, **kw):
            asked.append(url)
            return FetchResult(status=200, final_url=url, body="")

        with SessionLocal() as session:
            run_round(
                session,
                fetcher=fetcher,
                targets=self._targets(),
                ignore_cadence=True,
                pause_seconds=0,
                platforms={"youtube"},
                youtube_checker=None,
            )
        assert all("/t/" not in url for url in asked), asked
        assert len(asked) == 2

    def test_no_filter_still_checks_everything(self, db):
        from app.db import SessionLocal
        from app.recheck import FetchResult
        from app.recheck import run_round

        asked = []

        def fetcher(url, **kw):
            asked.append(url)
            return FetchResult(status=200, final_url=url, body="")

        with SessionLocal() as session:
            run_round(
                session,
                fetcher=fetcher,
                targets=self._targets(),
                ignore_cadence=True,
                pause_seconds=0,
                youtube_checker=None,
            )
        assert len(asked) == 3


class TestTheDashboardCanSeeNotes:
    """A platform with no capture table still has takedowns to show."""

    def test_a_format_gets_no_tab_of_its_own(self, session):
        """Decided on 2026-09-28, and it is a judgement about reading.

        图文 and video are the same accounts, found by the same tag
        searches, and the question worth asking is how the two compare.
        Behind a second tab that comparison is two page loads and an
        act of memory; in one table with a column it is a glance. So
        the platform keeps its own key -- that is what makes the
        comparison computable at all -- and the merge happens at the
        point of display.
        """
        from app.clock import now as utc_now
        from app.dashboard import measured_platforms
        from app.models import SharedLink

        session.add(
            SharedLink(
                participant_id="P001",
                platform="douyin_note",
                raw_text="x",
                video_id="7689",
                canonical_url="https://www.douyin.com/note/7689",
                shared_at=utc_now(),
                source="pasted",
            )
        )
        session.commit()

        known = measured_platforms(session)
        assert "douyin_note" not in known
        assert {"douyin", "tiktok", "youtube"} <= set(known)

    def test_the_notes_are_counted_under_douyin(self, session):
        from app.clock import now as utc_now
        from app.models import LinkCheck, SharedLink
        from app.survival import findings

        session.add(
            SharedLink(
                participant_id="P001",
                platform="douyin_note",
                raw_text="x",
                video_id="7689",
                canonical_url="https://www.douyin.com/note/7689",
                shared_at=utc_now(),
                source="pasted",
            )
        )
        session.add(
            LinkCheck(
                platform="douyin_note",
                video_id="7689",
                target_kind="video",
                url="https://www.douyin.com/note/7689",
                http_status=200,
                evidence="id confirmed",
                checked_at=utc_now(),
            )
        )
        session.commit()

        assert any(f.video_id == "7689" for f in findings(session, "douyin"))
        # And still findable on its own, for a comparison between them.
        assert any(f.video_id == "7689" for f in findings(session, "douyin_note"))
        assert not any(f.video_id == "7689" for f in findings(session, "tiktok"))

    def test_the_takedowns_view_serves_it(self, client):
        from app.clock import now as utc_now
        from app.db import SessionLocal
        from app.models import SharedLink

        with SessionLocal() as session:
            session.add(
                SharedLink(
                    participant_id="P001",
                    platform="douyin_note",
                    raw_text="x",
                    video_id="7689",
                    canonical_url="https://www.douyin.com/note/7689",
                    shared_at=utc_now(),
                    source="pasted",
                )
            )
            session.commit()

        answer = client.get(
            "/dashboard/takedowns",
            params={"platform": "douyin_note", "key": "test-admin-key"},
        )
        assert answer.status_code == 200
        assert "douyin_note" in answer.text

    def test_a_platform_nobody_has_data_for_is_still_refused(self, client):
        answer = client.get(
            "/dashboard/takedowns",
            params={"platform": "weibo", "key": "test-admin-key"},
        )
        assert answer.status_code == 404


class TestTheKindColumn:
    """One table, a column saying which -- not two tabs."""

    def test_a_note_row_is_marked_and_a_video_row_is_not(self):
        from app.dashboard import _kind_cell

        class Row:
            def __init__(self, platform):
                self.platform = platform

        assert "图文" in _kind_cell(Row("douyin_note"))
        assert "图文" not in _kind_cell(Row("douyin"))
        assert "图文" not in _kind_cell(Row("tiktok"))

    def test_the_douyin_listing_includes_pasted_notes(self, session):
        """They have no capture row, so this listing is their only one."""
        from app.clock import now as utc_now
        from app.models import SharedLink
        from app.views import video_rows

        for video_id, platform in (("111", "douyin"), ("222", "douyin_note")):
            session.add(
                SharedLink(
                    participant_id="P001",
                    platform=platform,
                    raw_text="拉拉们都是怎么谈上的啊 #lwl #le",
                    video_id=video_id,
                    canonical_url=f"https://www.douyin.com/note/{video_id}",
                    shared_at=utc_now(),
                    source="pasted",
                )
            )
        session.commit()

        found = {row.video_id: row.platform for row in video_rows(session, "douyin", 50)}
        assert found.get("111") == "douyin"
        assert found.get("222") == "douyin_note"
