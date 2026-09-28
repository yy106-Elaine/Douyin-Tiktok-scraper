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
