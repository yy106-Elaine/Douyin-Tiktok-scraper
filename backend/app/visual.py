"""Visual coding of the archived posts, one call per post.

    ./.venv/bin/pip install -r requirements-visual.txt
    ./.venv/bin/python -m app.visual --platform douyin_note --limit 30
    ./.venv/bin/python -m app.visual --platform douyin_note --limit 30 --apply

The codebook is `docs/prompts/video-codebook.zh.md`; this module
carries it to the model and writes down what comes back. Three
properties of that journey are not incidental:

**Blind to the outcome.** Nothing about removal, dates, or engagement
is sent. The whole point of coding appearance is to ask later whether
appearance predicts removal, and a coder who knows the answer is not
measuring the question.

**Refusals and malformed replies are recorded, not retried away.** A
post the model will not code is data about that post -- these are
videos of queer people, and a model declining to describe them is a
finding about the instrument, not noise to be cleaned. The raw text
is kept and the row is marked, rather than the call being repeated
until something parseable comes out.

**The reply's shape is enforced, its content is not.** `SCHEMA` goes
to the API as a structured-output format, so a malformed reply cannot
come back and the only unparseable outcome left is a refusal -- which
is exactly the outcome worth counting. The codebook stays the
authority on what each field *means*; this file is only the authority
on what shape it arrives in.

**One line per post, appended.** A run that dies halfway has coded
everything up to that point, and `--resume` skips what is already
written. 560 posts at a few seconds each is not a thing to start over.

What is *not* here is any analysis. The fields come back, they go in
a file, and the indices get built later where a reader can see the
rule. The old Appendix B built its index inside the prompt, which is
how a codebook came to define its own finding.
"""
from __future__ import annotations

import argparse
import base64
import json
import random
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import local_date
from .models import WebVideo

#: Per post. A 图文 can run to twenty cards and the first few carry
#: the subject; the tail is usually more of the same. Capped because
#: the cost is per image and the twentieth adds little.
MAX_IMAGES = 8

#: Where the codebook lives, read at run time rather than copied into
#: this file: one text, and a change to it is a change to the run.
PROMPT_FILE = "docs/prompts/video-codebook.zh.md"

#: Everything between these two markers in the codebook is the prompt.
PROMPT_START = "## Prompt 全文"
PROMPT_END = "## 跑之前还要做的"


def prompt_text(repo_root: Path) -> str:
    """The prompt, lifted out of the codebook's own fenced block.

    Kept in the codebook rather than in code so that the text a
    reviewer reads and the text the model receives cannot drift
    apart. A thesis appendix that does not match what ran is worse
    than no appendix.
    """
    source = (repo_root / PROMPT_FILE).read_text(encoding="utf-8")
    start = source.index(PROMPT_START)
    end = source.index(PROMPT_END, start)
    block = source[start:end]
    fenced = block.split("```")
    if len(fenced) < 2:
        raise ValueError(f"no fenced prompt block in {PROMPT_FILE}")
    return fenced[1].strip()


@dataclass
class Post:
    """One archived post, and the files that are actually on disk."""

    video_id: str
    platform: str
    images: list[Path] = field(default_factory=list)
    video: Path | None = None

    @property
    def codable(self) -> bool:
        return bool(self.images or self.video)


def collected_within(session: Session, since: date | None,
                     until: date | None) -> set[str] | None:
    """Video ids first collected inside a window of collection days.

    The window is on *first collection*, not on publication: the
    corpus is what this study could see, and a post enters it the day
    it was first captured. Reusing `survival._collected_by_video`
    keeps that definition in one place, so the window a coding run
    used and the window the cohort chart draws are the same window.

    Returns None when no window was asked for, which means no filter.
    """
    if since is None and until is None:
        return None
    from .survival import _collected_by_video

    # Every platform, not this one: `_collected_by_video` keys off the
    # structured tables, and `douyin_note` is not one of them -- 图文
    # rows live in the Douyin table under their own platform column.
    # Asking for "douyin_note" would quietly come back empty, which is
    # the kind of filter that silently codes nothing. Ids are unique
    # across platforms, so the caller's own platform filter is what
    # narrows this.
    inside: set[str] = set()
    for video_id, captured_at in _collected_by_video(session, None).items():
        day = local_date(captured_at)
        if day is None:
            continue
        if since is not None and day < since:
            continue
        if until is not None and day > until:
            continue
        inside.add(video_id)
    return inside


def archived(session: Session, platform: str,
             since: date | None = None,
             until: date | None = None) -> list[Post]:
    """Posts of this platform whose files are on disk right now.

    The database records a download; the disk is what can be coded.
    A row whose folder was emptied is not a post this can look at,
    and saying so here is cheaper than a failure per call.

    `since`/`until` narrow it to posts first collected in that window
    of local days, both ends included.
    """
    window = collected_within(session, since, until)
    found: list[Post] = []
    for row in session.scalars(
        select(WebVideo).where(
            WebVideo.platform == platform, WebVideo.local_path.isnot(None)
        )
    ):
        if window is not None and row.video_id not in window:
            continue
        path = Path(row.local_path or "")
        post = Post(video_id=row.video_id, platform=platform)
        if path.is_dir():
            post.images = sorted(
                child for child in path.iterdir()
                if child.is_file() and child.suffix.lower() in
                {".jpg", ".jpeg", ".png", ".webp"}
            )[:MAX_IMAGES]
        elif path.is_file():
            post.video = path
        if post.codable:
            found.append(post)
    return found


def sample(posts: list[Post], limit: int | None, seed: int) -> list[Post]:
    """A random sample, and deliberately not a stratified one.

    Stratifying a calibration sample by outcome would put the removal
    status into the room while the codebook is still being judged.
    The seed is fixed so the same thirty come back on a re-run and
    two people can look at the same posts.
    """
    ordered = sorted(posts, key=lambda post: post.video_id)
    if limit is None or limit >= len(ordered):
        return ordered
    return random.Random(seed).sample(ordered, limit)


def already_done(path: Path) -> set[str]:
    """Video ids this output file already holds."""
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            done.add(json.loads(line)["video_id"])
        except (ValueError, KeyError):
            continue
    return done


def parse(raw: str) -> tuple[dict | None, str]:
    """The model's reply as a dict, or None and why not.

    A reply that is not JSON is kept verbatim. It is tempting to ask
    again until something parses, and that is how a refusal becomes
    invisible: the post that took four attempts looks exactly like
    the post that took one.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        found = json.loads(text)
    except ValueError as error:
        return None, f"not JSON: {error}"
    if not isinstance(found, dict):
        return None, "JSON was not an object"
    return found, ""


#: Claude tokenises an image by pixel area, at roughly one token per
#: 28x28 patch. So the bill is set by resolution, not by how much is
#: in the picture -- a 1080x1440 card costs about 2,000 tokens, and a
#: full-resolution one can reach ~4,800. Downscaling the long edge is
#: the single biggest cost lever in this pass.
PATCH = 28 * 28

#: What the long edge is reduced to before sending. 1568 keeps a card
#: legible enough to read the text printed on it -- which is where
#: most of a 图文's content lives -- while costing roughly half of
#: full resolution. Lower it for cheaper runs, but check section F
#: afterwards: on-screen text is the first thing downscaling loses.
MAX_EDGE = 1568

#: Input / output dollars per million tokens, for the estimate. The
#: cheapest model that holds the codebook is the right one here --
#: these are enum choices from a picture, not reasoning -- but which
#: model that is has to be measured on the sample, not assumed. Batch
#: pricing is half of these.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

#: The shape of a reply, enforced by the API rather than hoped for.
#: The codebook is the authority on what each field *means*; this is
#: the authority on what comes back, so a malformed reply cannot
#: happen and the only unparseable outcome left is a refusal.
SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "people_visible", "primary_subject", "face_visible",
        "coding_possible", "subject", "second_person",
        "presentation_distance", "apparent_minors",
        "two_people_together", "physical_affection", "presented_as_couple",
        "onscreen_tph_terms", "onscreen_wlw_terms",
        "onscreen_relationship_terms", "onscreen_moderation_terms",
        "onscreen_contact", "confidence", "notes",
    ],
    "properties": {
        # Banded, not counted. A pilot post held a class photo and the
        # model reported 140 people -- a number about whether there is
        # a group shot, not about who the post is presenting.
        "people_visible": {"enum": ["0", "1", "2", "3-5", "6+"]},
        "primary_subject": {"enum": ["single", "pair", "group", "none"]},
        "face_visible": {"type": "boolean"},
        "coding_possible": {"type": "boolean"},
        "subject": {"anyOf": [{"$ref": "#/$defs/person"}, {"type": "null"}]},
        "second_person": {
            "anyOf": [{"$ref": "#/$defs/person"}, {"type": "null"}]},
        "presentation_distance": {
            "anyOf": [{"type": "integer", "minimum": 1, "maximum": 5},
                      {"type": "null"}]},
        # For protection and exclusion. Never a predictor.
        "apparent_minors": {"enum": ["none", "possible", "clear"]},
        "two_people_together": {"type": "boolean"},
        "physical_affection": {
            "enum": ["none", "proximity", "hand_holding", "embrace", "kiss"]},
        "presented_as_couple": {"type": "boolean"},
        "onscreen_tph_terms": {"type": "array", "items": {"type": "string"}},
        "onscreen_wlw_terms": {"type": "array", "items": {"type": "string"}},
        "onscreen_relationship_terms": {
            "type": "array", "items": {"type": "string"}},
        "onscreen_moderation_terms": {
            "type": "array", "items": {"type": "string"}},
        "onscreen_contact": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "notes": {"type": "string"},
    },
    "$defs": {
        "person": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "hair_length", "hair_mullet", "hair_undercut", "hair_dyed",
                "makeup_visible", "upper_garment", "menswear_items",
                "chest_presentation", "skin_exposure", "stance_wide",
                "hands_in_pockets", "arms_crossed", "gaze_direct",
                "head_tilt_or_chin_tuck", "peace_sign_or_heart",
                "hand_gesture_dance", "full_body_dance", "lip_sync",
            ],
            "properties": {
                "hair_length": {"enum": [
                    "shaved", "cropped_above_ear", "ear_to_jaw",
                    "jaw_to_shoulder", "below_shoulder", "not_visible"]},
                "hair_mullet": {"type": "boolean"},
                "hair_undercut": {"type": "boolean"},
                "hair_dyed": {"type": "boolean"},
                "makeup_visible": {
                    "enum": ["none", "light", "heavy", "not_visible"]},
                "upper_garment": {
                    "enum": ["fitted", "loose_or_boxy", "not_visible"]},
                "menswear_items": {
                    "type": "array",
                    "items": {"enum": [
                        "necktie", "suit_jacket", "oversized_shirt",
                        "sports_jersey", "cap", "chain", "none"]}},
                "chest_presentation": {"enum": [
                    "flattened_or_bound", "unmodified", "not_visible"]},
                "skin_exposure": {"enum": [
                    "covered", "arms_or_shoulders", "midriff_or_legs",
                    "not_visible"]},
                "stance_wide": {"type": "boolean"},
                "hands_in_pockets": {"type": "boolean"},
                "arms_crossed": {"type": "boolean"},
                "gaze_direct": {"type": "boolean"},
                "head_tilt_or_chin_tuck": {"type": "boolean"},
                "peace_sign_or_heart": {"type": "boolean"},
                "hand_gesture_dance": {"type": "boolean"},
                "full_body_dance": {"type": "boolean"},
                "lip_sync": {"type": "boolean"},
            },
        }
    },
}


def shrink(path: Path, max_edge: int) -> tuple[bytes, str, tuple[int, int]]:
    """The image, no larger than `max_edge` on its long side.

    Returns the bytes to send, their media type, and the dimensions
    they ended up at. An image already within the limit is sent as it
    is, byte for byte -- re-encoding a JPEG to shrink it by nothing
    would lose quality for no saving.
    """
    import io

    from PIL import Image

    with Image.open(path) as picture:
        width, height = picture.size
        if max(width, height) <= max_edge:
            kind = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            return path.read_bytes(), kind, (width, height)

        scale = max_edge / max(width, height)
        size = (round(width * scale), round(height * scale))
        smaller = picture.convert("RGB").resize(size, Image.LANCZOS)

    buffer = io.BytesIO()
    smaller.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue(), "image/jpeg", size


def image_tokens(size: tuple[int, int]) -> int:
    """Roughly what an image of this size costs, before it is sent.

    An approximation of the server's own tokenizer, good enough to
    choose a model and a resolution by. `--exact` replaces it with a
    real `count_tokens` call when there are credentials to make one.
    """
    width, height = size
    return round(width * height / PATCH)


def _content(post: Post, prompt: str, max_edge: int = MAX_EDGE) -> list[dict]:
    """The images, then the prompt. Images first so the text is last read."""
    blocks: list[dict] = []
    for image in post.images:
        blob, kind, _ = shrink(image, max_edge)
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": kind,
                "data": base64.standard_b64encode(blob).decode("utf-8"),
            },
        })
    blocks.append({"type": "text", "text": prompt})
    return blocks


def code_one(client, post: Post, prompt: str, model: str,
             effort: str, max_edge: int = MAX_EDGE) -> dict:
    """One post, one call. Returns the row to write, whatever happened.

    No `fallbacks`. The SDK guidance is to enable server-side fallback
    on a refusal, and for most applications that is right -- but here
    it would silently route some posts to a different model, and a
    corpus coded by two instruments is worse than a corpus with a
    recorded gap. A refusal is written down and left as a refusal.
    """
    import anthropic

    row: dict = {
        "video_id": post.video_id,
        "platform": post.platform,
        "images_sent": len(post.images),
        "model": model,
        "effort": effort,
        "max_edge": max_edge,
    }
    try:
        answer = client.messages.create(
            model=model,
            max_tokens=8000,
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[{
                "role": "user",
                "content": _content(post, prompt, max_edge)}],
        )
    except anthropic.APIStatusError as error:
        row["error"] = f"{type(error).__name__} {error.status_code}"
        return row
    except anthropic.APIConnectionError as error:
        row["error"] = f"{type(error).__name__}: {error}"
        return row

    row["usage"] = {
        "input": answer.usage.input_tokens,
        "output": answer.usage.output_tokens,
    }

    # Always before reading content: a safety classifier may decline,
    # and that arrives as a 200 with a category rather than an error.
    if answer.stop_reason == "refusal":
        detail = getattr(answer, "stop_details", None)
        row["error"] = "refusal"
        row["refusal_category"] = getattr(detail, "category", None)
        return row
    if answer.stop_reason == "max_tokens":
        row["error"] = "hit max_tokens"
        return row

    text = next((b.text for b in answer.content if b.type == "text"), "")
    coded, why = parse(text)
    if coded is None:
        row["error"] = why
        row["raw"] = text[:2000]
        return row
    row["coding"] = coded
    return row


def estimate(posts: list[Post], prompt: str, max_edge: int,
             client=None, model: str = "", whole: int = 0) -> None:
    """What the run really costs, measured from the actual pictures.

    Works with no credentials: image tokens come from pixel area,
    which is how the server charges for them anyway. Pass a client to
    replace the approximation with a real `count_tokens` call.
    """
    from PIL import Image

    tokens = 0
    full = 0
    sizes: list[int] = []
    for post in posts:
        for path in post.images:
            with Image.open(path) as picture:
                width, height = picture.size
            full += image_tokens((width, height))
            scale = min(1.0, max_edge / max(width, height, 1))
            shrunk = (round(width * scale), round(height * scale))
            tokens += image_tokens(shrunk)
            sizes.append(max(width, height))
    # The prompt rides along with every post, which at 560 posts is
    # not a rounding error.
    tokens += len(posts) * len(prompt) // 3

    if client is not None:
        counted = 0
        for post in posts:
            counted += client.messages.count_tokens(
                model=model,
                messages=[{
                    "role": "user",
                    "content": _content(post, prompt, max_edge)}],
            ).input_tokens
        print(f"\ncounted exactly: {counted:,} input tokens "
              f"(approximation said {tokens:,})")
        tokens = counted

    images = sum(len(post.images) for post in posts)
    typical = sorted(sizes)[len(sizes) // 2] if sizes else 0
    print(f"\n{len(posts)} post(s), {images} image(s); "
          f"long edge typically {typical}px, sent at most {max_edge}px")
    print(f"{tokens:,} input tokens "
          f"({tokens / max(len(posts), 1):,.0f} per post)")
    if full > tokens:
        print(f"full resolution would be {full:,} — "
              f"downscaling saves {(1 - tokens / full) * 100:.0f}%")

    out_per_post = 1200
    corpus = whole or len(posts)
    print(f"\n{'model':20} {'this sample':>12} {'all ' + str(corpus):>10} "
          f"{str(corpus) + ' batched':>14}")
    for name, (dollars_in, dollars_out) in PRICES.items():
        here = (tokens * dollars_in
                + len(posts) * out_per_post * dollars_out) / 1_000_000
        total = here / max(len(posts), 1) * corpus
        print(f"{name:20} {'$' + format(here, '.2f'):>12} "
              f"{'$' + format(total, '.2f'):>10} "
              f"{'$' + format(total / 2, '.2f'):>14}")
    print("\n  Batched is the Batch API: half price, hours not seconds.")
    print("  Output is assumed at 1,200 tokens per post — one filled-in "
          "schema plus thinking.")


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin_note",
                        choices=["douyin_note", "douyin"])
    parser.add_argument("--limit", type=int, default=30,
                        help="how many posts to code (default 30)")
    parser.add_argument("--seed", type=int, default=11,
                        help="fixed, so a re-run gets the same sample")
    parser.add_argument("--since", type=date.fromisoformat, default=None,
                        metavar="YYYY-MM-DD",
                        help="only posts first collected on or after this "
                             "day (collection day, not publication day)")
    parser.add_argument("--until", type=date.fromisoformat, default=None,
                        metavar="YYYY-MM-DD",
                        help="only posts first collected on or before this "
                             "day; with --since this is the coding window")
    parser.add_argument("--out", default="visual-coding.jsonl",
                        help="one JSON object per post, appended")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="high",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--apply", action="store_true",
                        help="actually call the model")
    parser.add_argument("--resume", action="store_true",
                        help="skip posts already in --out")
    parser.add_argument("--estimate", action="store_true",
                        help="price the run from the real images, without "
                             "coding anything and without credentials")
    parser.add_argument("--exact", action="store_true",
                        help="with --estimate: replace the approximation "
                             "with a real count_tokens call (needs a key)")
    parser.add_argument("--max-edge", type=int, default=MAX_EDGE,
                        help=f"shrink each image's long edge to this before "
                             f"sending (default {MAX_EDGE}; lower is cheaper "
                             f"and reads on-screen text less well)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    prompt = prompt_text(repo_root)

    init_db()
    with SessionLocal() as session:
        posts = archived(session, args.platform, args.since, args.until)

    chosen = sample(posts, args.limit, args.seed)
    out = Path(args.out)
    if args.resume:
        done = already_done(out)
        chosen = [post for post in chosen if post.video_id not in done]

    window = ""
    if args.since or args.until:
        window = (f", first collected {args.since or 'any'} "
                  f"to {args.until or 'any'}")
    print(f"{len(posts)} archived {args.platform} post(s) on disk{window}; "
          f"{len(chosen)} to code")

    if args.estimate:
        client = None
        if args.exact:
            import anthropic

            client = anthropic.Anthropic()
        estimate(chosen, prompt, args.max_edge, client, args.model,
                 whole=len(posts))
        return

    if not args.apply:
        for post in chosen[:10]:
            what = (f"{len(post.images)} image(s)" if post.images
                    else post.video.name if post.video else "?")
            print(f"  {post.video_id}  {what}")
        if len(chosen) > 10:
            print(f"  ... and {len(chosen) - 10} more")
        print(f"\nprompt is {len(prompt)} characters, from {PROMPT_FILE}")
        print("Add --apply to call the model.")
        return

    try:
        import anthropic
    except ModuleNotFoundError:
        raise SystemExit(
            "The anthropic SDK is not installed.\n"
            "  ./.venv/bin/pip install -r requirements-visual.txt"
        ) from None

    # Zero-arg: resolves ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN,
    # then an `ant auth login` profile. `ant auth status` says which.
    client = anthropic.Anthropic()

    coded = refused = failed = 0
    with out.open("a", encoding="utf-8") as handle:
        for index, post in enumerate(chosen, start=1):
            row = code_one(client, post, prompt, args.model, args.effort,
                           args.max_edge)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            if "coding" in row:
                coded += 1
                said = row["coding"].get("presentation_distance")
                mark = f"distance {said}" if said is not None else "null"
            elif row.get("error") == "refusal" or "raw" in row:
                refused += 1
                mark = f"REFUSED/UNUSABLE — {row['error'][:60]}"
            else:
                failed += 1
                mark = f"ERROR — {row['error'][:60]}"
            print(f"[{index}/{len(chosen)}] {post.video_id}  {mark}",
                  flush=True)

    print(f"\ncoded {coded}; {refused} refused or unusable; "
          f"{failed} call failed")
    print(f"written to {out}")


if __name__ == "__main__":  # pragma: no cover
    main()
