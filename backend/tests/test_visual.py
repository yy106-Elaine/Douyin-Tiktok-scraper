"""The visual coding runner: sampling, parsing, and what it refuses to hide."""
from __future__ import annotations

import pytest

import json
from datetime import datetime
from pathlib import Path

from app.db import SessionLocal
from app.models import WebVideo
from app.visual import (
    MAX_IMAGES,
    Post,
    already_done,
    archived,
    parse,
    prompt_text,
    sample,
)

ROOT = Path(__file__).resolve().parents[2]


def test_the_prompt_comes_out_of_the_codebook() -> None:
    """One text, so the appendix and the run cannot drift apart.

    A thesis appendix that does not match what actually ran is worse
    than no appendix, so the prompt is read from the codebook at run
    time rather than copied into code.
    """
    prompt = prompt_text(ROOT)

    assert "presentation_distance" in prompt
    assert "onscreen_tph_terms" in prompt
    # The three rules that make the fields mean anything.
    assert "看不清" in prompt
    assert "不要判断这个人是谁" in prompt
    # And the one instruction that keeps the coding blind.
    assert "是否" in prompt and "敏感" in prompt


def test_a_reply_that_is_not_json_is_kept_whole() -> None:
    """Retrying until something parses is how a refusal disappears.

    A post that took four attempts would look exactly like a post
    that took one. These are videos of queer people; a model
    declining to describe them is a finding about the instrument.
    """
    found, why = parse("I can't help with analysing images of people.")
    assert found is None
    assert "not JSON" in why

    found, why = parse('{"presentation_distance": 4}')
    assert found == {"presentation_distance": 4}
    assert why == ""


def test_a_fenced_reply_is_unwrapped() -> None:
    """Models fence JSON whether or not they were asked to."""
    found, _ = parse('```json\n{"confidence": 0.8}\n```')
    assert found == {"confidence": 0.8}

    found, _ = parse('```\n{"confidence": 0.8}\n```')
    assert found == {"confidence": 0.8}


def test_a_json_array_is_not_a_coding() -> None:
    found, why = parse("[1, 2, 3]")
    assert found is None
    assert "not an object" in why


def test_the_sample_is_stable_and_not_stratified(db: None) -> None:
    """Same seed, same thirty -- so two people can look at one sample.

    And drawn at random rather than stratified by outcome: stratifying
    would put the removal status in the room while the codebook is
    still being judged.
    """
    posts = [Post(video_id=f"{n:04d}", platform="douyin_note",
                  images=[Path("a.jpg")]) for n in range(100)]

    first = [post.video_id for post in sample(posts, 10, seed=11)]
    again = [post.video_id for post in sample(posts, 10, seed=11)]
    assert first == again
    assert len(first) == 10

    other = [post.video_id for post in sample(posts, 10, seed=12)]
    assert other != first

    # Asking for more than there are returns everything, in order.
    assert len(sample(posts, 500, seed=11)) == 100


def test_only_posts_whose_files_are_on_disk_are_offered(
    db: None, tmp_path
) -> None:
    """The database records a download; the disk is what can be coded.

    A row whose folder was emptied is not a post this can look at, and
    saying so here is cheaper than one failed call per post.
    """
    folder = tmp_path / "7001"
    folder.mkdir()
    for index in range(1, 12):
        (folder / f"{index:02d}.jpg").write_bytes(b"\xff\xd8\xff")
    (folder / "03.jpg.part").write_bytes(b"partial")

    with SessionLocal() as session:
        session.add_all([
            WebVideo(platform="douyin_note", video_id="7001",
                     local_path=str(folder),
                     fetched_at=datetime(2026, 10, 1, 12, 0)),
            WebVideo(platform="douyin_note", video_id="7002",
                     local_path=str(tmp_path / "gone"),
                     fetched_at=datetime(2026, 10, 1, 12, 0)),
            WebVideo(platform="douyin_note", video_id="7003",
                     local_path=None,
                     fetched_at=datetime(2026, 10, 1, 12, 0)),
        ])
        session.commit()

        found = archived(session, "douyin_note")

    assert [post.video_id for post in found] == ["7001"]
    # Capped, in order, and the half-written file is not one of them.
    assert len(found[0].images) == MAX_IMAGES
    assert found[0].images[0].name == "01.jpg"
    assert all(image.suffix == ".jpg" for image in found[0].images)


def test_resume_reads_back_what_was_already_coded(tmp_path) -> None:
    """A run that dies halfway has coded everything up to that point."""
    out = tmp_path / "coding.jsonl"
    out.write_text(
        json.dumps({"video_id": "7001", "coding": {}}) + "\n"
        + "not json at all\n"
        + json.dumps({"video_id": "7002", "error": "HTTP 503"}) + "\n",
        encoding="utf-8",
    )

    # An errored post counts as done too: it is written down, and a
    # re-run that quietly retried it would hide the failure rate.
    assert already_done(out) == {"7001", "7002"}
    assert already_done(tmp_path / "nothing.jsonl") == set()


def test_the_schema_covers_every_field_the_codebook_defines() -> None:
    """The prompt and the schema are two halves of one contract.

    The codebook says what each field means; the schema says what
    shape it arrives in. A field defined in one and missing from the
    other is a column that silently never gets filled.
    """
    from app.visual import SCHEMA

    prompt = prompt_text(ROOT)
    top = set(SCHEMA["properties"])
    person = set(SCHEMA["$defs"]["person"]["properties"])

    for name in top | person:
        assert name in prompt, f"{name} is in the schema but not the prompt"

    # And the fields the analysis is built around are really there.
    assert {"presentation_distance", "physical_affection",
            "two_women_together"} <= top
    assert {"hair_length", "menswear_items", "gaze_direct"} <= person


def test_every_field_is_required_so_nothing_comes_back_half_filled() -> None:
    """A field the model may omit is a field that will be missing on
    exactly the posts that were hard to read -- which is the opposite
    of what the data needs. Everything is required; "cannot see" has
    its own value instead."""
    from app.visual import SCHEMA

    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])
    person = SCHEMA["$defs"]["person"]
    assert set(person["required"]) == set(person["properties"])
    # ...and nothing else may be invented.
    assert SCHEMA["additionalProperties"] is False
    assert person["additionalProperties"] is False


def test_an_image_within_the_limit_is_sent_untouched(tmp_path) -> None:
    """Re-encoding a JPEG to shrink it by nothing loses quality for free."""
    from PIL import Image

    from app.visual import shrink

    path = tmp_path / "small.jpg"
    Image.new("RGB", (800, 600), "white").save(path, quality=95)
    original = path.read_bytes()

    blob, kind, size = shrink(path, 1568)
    assert blob == original
    assert kind == "image/jpeg"
    assert size == (800, 600)


def test_a_large_image_is_shrunk_on_its_long_edge(tmp_path) -> None:
    """Claude charges for an image by pixel area, so the long edge is
    the lever. Aspect ratio has to survive it -- a squashed card is a
    different picture."""
    from PIL import Image

    from app.visual import image_tokens, shrink

    path = tmp_path / "big.jpg"
    Image.new("RGB", (2160, 3840), "white").save(path)

    _, _, size = shrink(path, 1568)
    assert max(size) == 1568
    assert abs(size[0] / size[1] - 2160 / 3840) < 0.01
    # ...and that is the saving the estimate promises.
    assert image_tokens(size) < image_tokens((2160, 3840)) / 2


def test_the_token_estimate_tracks_pixel_area() -> None:
    """Checked against the documented rate: ~1,200 tokens at 1280x720."""
    from app.visual import image_tokens

    assert 1100 <= image_tokens((1280, 720)) <= 1300
    # Twice the area, twice the cost.
    assert image_tokens((2560, 1440)) == pytest.approx(
        image_tokens((1280, 720)) * 4, rel=0.01)
