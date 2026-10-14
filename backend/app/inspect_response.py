"""What a saved response body actually contains, in twenty lines not twenty thousand.

    ./.venv/bin/python -m app.inspect_response peeked/7686334741608361451.responses.json

`app.peek` writes the bodies the site sent. For a page filed as
unreadable whose `aweme/detail` came back 200 and carried the id,
the question is no longer "did the record arrive" -- it did -- but
"what is in it that the parser found nothing in".

Prints the shape: the top-level keys, the status fields Douyin uses
to say no, whether the record object is present or null, and any
block that explains a refusal. Values are summarised, never dumped:
a record body is a megabyte and the answer is in its skeleton.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

#: Fields Douyin uses to say "here is your 200, and no, you cannot
#: have this". A record that is absent *with* one of these is a
#: different thing from a record that is absent because the page
#: never asked -- and the check currently files both as "read,
#: nothing on the page".
_REFUSAL_HINTS = (
    "status_code", "status_msg", "filter_detail", "filter_reason",
    "detail_msg", "prompts", "notice", "reason", "code", "message",
    "msg", "err_no", "error_code",
)
#: Where the record itself lives, depending on the endpoint.
_RECORD_KEYS = ("aweme_detail", "aweme_list", "aweme_info", "item_list")


def summarise(blob, depth: int = 0, limit: int = 3) -> list[str]:
    """The shape of a decoded body: keys, types, and sizes."""
    pad = "  " * depth
    out: list[str] = []
    if isinstance(blob, dict):
        for key, value in blob.items():
            if isinstance(value, dict):
                out.append(f"{pad}{key}: object ({len(value)} keys)")
                if depth < limit:
                    out.extend(summarise(value, depth + 1, limit))
            elif isinstance(value, list):
                out.append(f"{pad}{key}: list of {len(value)}")
                if value and depth < limit:
                    out.extend(summarise(value[0], depth + 1, limit))
            elif value is None:
                out.append(f"{pad}{key}: null")
            else:
                text = str(value)
                if len(text) > 90:
                    text = text[:90] + "…"
                out.append(f"{pad}{key}: {text}")
    return out


def report(path: Path) -> list[str]:
    lines: list[str] = []
    saved = json.loads(path.read_text(encoding="utf-8"))
    # peek writes a list of [url, body] pairs, or a dict of them.
    items = saved.items() if isinstance(saved, dict) else saved
    for entry in items:
        try:
            url, body = entry
        except (TypeError, ValueError):
            continue
        if "aweme/detail" not in str(url) and "aweme/post" not in str(url):
            continue
        lines.append(f"\n=== {url}")
        if not isinstance(body, dict):
            lines.append(f"  body is {type(body).__name__}, not an object")
            continue

        lines.append(f"  top-level keys: {', '.join(sorted(body))}")
        for key in _REFUSAL_HINTS:
            if key in body:
                value = body[key]
                if isinstance(value, (dict, list)):
                    lines.append(f"  {key}:")
                    lines.extend("  " + line
                                 for line in summarise(value, 1))
                else:
                    # Truncated here too. A refusal message is a
                    # sentence; a five-thousand-character one is a
                    # field that is not what it looks like, and
                    # printing it would bury the rest of the shape.
                    text = str(value)
                    if len(text) > 200:
                        text = text[:200] + "…"
                    lines.append(f"  {key}: {text}")
        for key in _RECORD_KEYS:
            if key in body:
                value = body[key]
                if value is None:
                    lines.append(f"  {key}: NULL — the record is not here")
                elif isinstance(value, list):
                    lines.append(f"  {key}: list of {len(value)}")
                else:
                    lines.append(
                        f"  {key}: object ({len(value)} keys) — present")
    if not lines:
        lines.append("no aweme/detail or aweme/post body in this file")
    return lines


def main() -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.files:
        print(f"\n######## {path.name}")
        for line in report(path):
            print(line)


if __name__ == "__main__":  # pragma: no cover
    main()
