"""Decide whether a collected video is about the topic under study.

A keyword search returns what the platform thinks matches the string,
not what the study is about. Chinese makes this much worse than usual,
because the search terms are substrings of unrelated words:

    女同  ->  女同桌 (deskmate), 女同学 (classmate), 女同事 (colleague)
    拉拉  ->  拉拉裤 (adult nappies), 货拉拉 (a delivery company),
              巴拉拉小魔仙 (a children's show), 拉拉队 (cheer squad)

and the results also carry escort advertising and AI-generated
material that is not community content at all.

So this marks each row instead of the collector silently dropping it.
A takedown study cannot afford a filter that deletes: a video excluded
by mistake is a video whose disappearance is never observed, and there
would be nothing in the data to notice. Every exclusion is stored with
its reason, the dashboard can show them, and changing the rules
re-marks the corpus rather than requiring it to be collected again.

`relevance` is None for a row that is in scope, and the reason string
for one that is out.

Only some of those reasons hide a row. The distinction is positive
evidence of noise against mere absence of evidence:

    hidden   an escort advert, an AI-generated clip, a nappy brand, a
             sentence about a classmate -- the text says what it is
    marked   no keyword in the text, no text at all, no Chinese in the
             text -- none of which proves the video is off topic

That line matters because the phone platforms often render a truncated
caption or none at all, and English-hashtag posts (#wlw #wlwtiktok)
are exactly the community content under study. Hiding those would have
thrown away hand-collected rows to save re-reading a few adverts.
"""
from __future__ import annotations

import re

#: Any CJK ideograph. Used for the "not in Chinese" check.
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

#: Terms that place a video in scope whatever else it contains. These
#: outrank the soft exclusions below, because 拉拉 colliding with a
#: product name elsewhere in the text does not matter once the text
#: also says 女同性恋.
#:
#: 拉拉 and 女同 need boundaries of their own, because they are both
#: the term being searched for and the substring that collides. Listed
#: bare, 拉拉 matched inside 拉拉裤 and then overrode the very exclusion
#: meant to catch it, so every packet of adult nappies stayed in the
#: corpus. The lookarounds name the collisions: a preceding 货/巴/芭/沙
#: or a following 裤/队/操/手 means the word is not the identity term.
STRONG = re.compile(
    r"女同性[恋戀]|同性[恋戀]|女同志|百合|蕾[丝絲][边邊]|"
    r"出[柜櫃]|女女|les\b|lesbian|lgbt|wlw|彩虹|"
    r"(?<![货貨巴芭沙])拉拉(?![裤褲队隊操手])|"
    r"女同(?![学學事胞僚桌])",
    re.IGNORECASE,
)

#: Exclusions nothing overrides: the video is not community content
#: regardless of which words appear beside it.
HARD: tuple[tuple[str, str], ...] = (
    # Escort and paid-contact advertising, which uses these keywords as
    # bait. A Telegram or WeChat contact plus a booking phrase is the
    # reliable signal.
    ("advertising", r"t\.me/|速[预預][约約]|加微信|包[养養]|外[围圍]|"
                    r"上[门門]服[务務]|[约約]炮"),
    # Synthetic content: not a real account posting about its own life,
    # so not what an interview study can follow up.
    ("ai generated", r"ai\s*[虚虛][拟擬]|ai\s*生成|ai\s*合成|ai\s*[换換][脸臉]|"
                     r"[虚虛][拟擬]女友|[虚虛][拟擬]主播"),
)

#: Exclusions a STRONG term overrides -- the keyword matched something
#: incidental rather than the topic.
SOFT: tuple[tuple[str, str], ...] = (
    # 女同 inside an ordinary word about school or work.
    ("not about the topic", r"女同桌|女同[学學]|女同事|女同胞|女同僚"),
    # 拉拉 inside a product or brand name.
    ("unrelated product", r"拉拉[裤褲]|[货貨]拉拉|[巴芭]拉拉|拉拉[队隊]|拉拉操|"
                          r"拉拉手|沙拉拉"),
)

#: Reasons that keep a row out of the default view. Everything else
#: is recorded and still shown.
HIDDEN = frozenset(
    {"advertising", "ai generated", "unrelated product", "not about the topic"}
)

_HARD = tuple((reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in HARD)
_SOFT = tuple((reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in SOFT)


def classify(*parts: object) -> str | None:
    """None when the text is in scope, else why it is not.

    Takes the title and description together, since either can carry
    the signal.
    """
    text = "\n".join(str(part) for part in parts if part)
    if not text.strip():
        return "no text"

    for reason, pattern in _HARD:
        if pattern.search(text):
            return reason

    strong = bool(STRONG.search(text))
    for reason, pattern in _SOFT:
        if pattern.search(text) and not strong:
            return reason

    # The study is of Chinese-language content, so a result with no
    # Chinese in it is out of scope even when the keyword matched.
    if not _CJK.search(text):
        return "not in chinese"

    if not strong:
        return "no topic term"
    return None


def remark(session) -> dict[str, int]:
    """Recompute `relevance` for every stored row. Returns the tally.

    The rules above will be wrong at first -- they are a list of
    collisions someone noticed, and the next collection run will show
    more. This is what makes that survivable: the verbatim payload is
    kept for every observation, so a corrected rule set is applied to
    the whole corpus by re-reading it. Nothing has to be collected
    again, and no judgement is frozen at the moment of collection.
    """
    import json

    from sqlalchemy import select

    from .models import CaptureEvent
    from .parsers import PLATFORM_TABLES

    payloads: dict[int, dict] = {}
    for event in session.scalars(select(CaptureEvent)):
        try:
            payloads[event.id] = json.loads(event.payload)
        except (TypeError, ValueError):
            payloads[event.id] = {}

    tally: dict[str, int] = {}
    changed = 0
    for model, _ in PLATFORM_TABLES.values():
        for post in session.scalars(select(model)):
            payload = payloads.get(post.capture_event_id, {})
            reason = classify(
                payload.get("caption") or post.caption,
                payload.get("description"),
            )
            if post.relevance != reason:
                post.relevance = reason
                changed += 1
            key = reason or "in scope"
            tally[key] = tally.get(key, 0) + 1
    if changed:
        session.commit()
    tally["changed"] = changed
    return tally


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        tally = remark(session)
        changed = tally.pop("changed", 0)
        for reason, count in sorted(tally.items(), key=lambda pair: -pair[1]):
            print(f"{count:6}  {reason}")
        print(f"\n{changed} row(s) re-marked")


if __name__ == "__main__":  # pragma: no cover
    main()
