"""Visual coding of the archived posts, one call per post.

    ./.venv/bin/python -m app.visual --platform douyin_note --limit 30 --dry-run
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
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def archived(session: Session, platform: str) -> list[Post]:
    """Posts of this platform whose files are on disk right now.

    The database records a download; the disk is what can be coded.
    A row whose folder was emptied is not a post this can look at,
    and saying so here is cheaper than a failure per call.
    """
    found: list[Post] = []
    for row in session.scalars(
        select(WebVideo).where(
            WebVideo.platform == platform, WebVideo.local_path.isnot(None)
        )
    ):
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


def _parts(post: Post) -> list[dict]:
    """The images, inline, as the Gemini REST body wants them."""
    out = []
    for image in post.images:
        kind = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        out.append({
            "inline_data": {
                "mime_type": kind,
                "data": base64.b64encode(image.read_bytes()).decode("ascii"),
            }
        })
    return out


def code_one(post: Post, prompt: str, model: str, api_key: str) -> dict:
    """One post, one call. Returns the row to write, whatever happened."""
    import urllib.error
    import urllib.request

    body = {
        "contents": [{"parts": [{"text": prompt}] + _parts(post)}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 2048},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    row: dict = {
        "video_id": post.video_id,
        "platform": post.platform,
        "images_sent": len(post.images),
        "model": model,
    }
    try:
        with urllib.request.urlopen(request, timeout=180) as answer:
            payload = json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        row["error"] = f"HTTP {error.code}: {error.read()[:300].decode('utf-8', 'replace')}"
        return row
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed
        row["error"] = f"{type(error).__name__}: {error}"
        return row

    try:
        raw = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        # A blocked or empty candidate. The reason is the finding.
        row["error"] = "no text in reply"
        row["raw"] = json.dumps(payload)[:1000]
        return row

    coded, why = parse(raw)
    if coded is None:
        row["error"] = why
        row["raw"] = raw[:2000]
        return row
    row["coding"] = coded
    return row


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin_note",
                        choices=["douyin_note", "douyin"])
    parser.add_argument("--limit", type=int, default=30,
                        help="how many posts to code (default 30)")
    parser.add_argument("--seed", type=int, default=11,
                        help="fixed, so a re-run gets the same sample")
    parser.add_argument("--out", default="visual-coding.jsonl",
                        help="one JSON object per post, appended")
    parser.add_argument("--model", default=os.environ.get(
        "GEMINI_MODEL", "gemini-2.0-flash"))
    parser.add_argument("--apply", action="store_true",
                        help="actually call the model")
    parser.add_argument("--resume", action="store_true",
                        help="skip posts already in --out")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    prompt = prompt_text(repo_root)

    init_db()
    with SessionLocal() as session:
        posts = archived(session, args.platform)

    chosen = sample(posts, args.limit, args.seed)
    out = Path(args.out)
    if args.resume:
        done = already_done(out)
        chosen = [post for post in chosen if post.video_id not in done]

    print(f"{len(posts)} archived {args.platform} post(s) on disk; "
          f"{len(chosen)} to code")
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

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
        "GOOGLE_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "No GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment.\n"
            "Put it in backend/.env or export it for this shell."
        )

    coded = refused = failed = 0
    with out.open("a", encoding="utf-8") as handle:
        for index, post in enumerate(chosen, start=1):
            row = code_one(post, prompt, args.model, api_key)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            if "coding" in row:
                coded += 1
                said = row["coding"].get("presentation_distance")
                mark = f"distance {said}" if said is not None else "null"
            elif "raw" in row:
                refused += 1
                mark = f"UNPARSEABLE — {row['error'][:60]}"
            else:
                failed += 1
                mark = f"ERROR — {row['error'][:60]}"
            print(f"[{index}/{len(chosen)}] {post.video_id}  {mark}",
                  flush=True)

    print(f"\ncoded {coded}; {refused} reply not usable; {failed} call failed")
    print(f"written to {out}")


if __name__ == "__main__":  # pragma: no cover
    main()
