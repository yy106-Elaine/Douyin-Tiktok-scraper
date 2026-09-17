"""Decide whether a collected video is Chinese-language WLW content.

The study is of 中国女同性恋 content, so that is what this requires:
the text must be in Chinese **and** carry a term placing it on topic.
Everything else is out. That is stricter than filtering out noise as it
is noticed, and it is the right way round -- a keyword search returns
what the platform matched, and in Chinese the search terms sit inside
unrelated words:

    女同  ->  女同桌 (deskmate), 女同学 (classmate), 女同事 (colleague)
    拉拉  ->  拉拉裤 (adult nappies), 货拉拉 (a delivery company),
              巴拉拉小魔仙 (a children's show), 拉拉队 (cheer squad)

and the rest of the results are escort advertising that uses the
keywords as bait, AI-generated clips, divination lessons where 女同志
means "female client", and videos in other languages entirely.

**Rows are marked, never dropped.** A video a filter deletes is a video
whose disappearance can never be observed, and nothing in the data
would show it had been there -- the one failure a takedown study cannot
detect after the fact. Every exclusion is stored with its reason, the
dashboard reaches them with `?show=all`, and `python -m app.relevance`
re-marks the whole corpus from the stored payloads when a rule changes.

One carve-out, in `app/views.py` rather than here: a Douyin or TikTok
row whose link was copied by hand is never hidden. Those were chosen
one at a time by a person, their captions are often truncated to
"...more" or missing, and the text is therefore no evidence about the
video. Hiding them would discard the rows that cost the most to
collect.

`relevance` is None for a row in scope, and the reason string
otherwise.
"""
from __future__ import annotations

import re

#: Any CJK ideograph. Used for the "not in Chinese" check.
#: Any CJK ideograph. Necessary but nowhere near sufficient: Japanese
#: uses the same block, so this alone called 百合ヶ浜 Chinese.
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: Hiragana and katakana, which Chinese does not use at all. This is
#: what actually separates the two languages, and it had to be added
#: after a real run returned a hundred Japanese yuri videos: 百合 is
#: the Japanese word for the same genre, so every one of them matched
#: the topic term and passed a "contains CJK" test.
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")

#: Terms that place a video on topic on their own. Unambiguous: no
#: ordinary sentence uses these to mean something else.
ALONE = re.compile(
    r"女同性[恋戀]|蕾[丝絲][边邊]|出[柜櫃]|女女|女同志|"
    r"lesbian|wlw|\bles\b|"
    # Self-identification, which is unambiguous even though it contains
    # an otherwise ambiguous term: no tour bus is 是拉拉.
    r"是拉拉|做拉拉|[当當]拉拉|[作]?[为為]拉拉|拉拉身份",
    re.IGNORECASE,
)

#: The search keywords that are also fragments of unrelated words. A
#: blocklist for these does not converge. One real run produced 拉拉車,
#: 拉拉山, 拉拉秧, 傲拉拉, 朵拉拉, 拉諾拉拉庫, 鬍子拉拉, 烤拉拉,
#: 拉拉草莓, and 女同 inside 父女同框, 母女同囚, 仔女同住, 呀女同我講
#: -- a list that grows with every run and never finishes.
#:
#: So these count only alongside a second signal. That is what actually
#: separates them: every genuinely relevant row in that run carried
#: something else as well (les, lesbian, 女生, 情侣, 意定监护), and not
#: one of the collisions carried anything.
AMBIGUOUS = re.compile(r"拉拉|女同|百合|姬", re.IGNORECASE)

#: Not enough on its own, but enough to confirm an ambiguous term.
COMPANION = re.compile(
    # Not bare 女生: "港女同內地女生有咩分別" is about girls from two
    # cities, and matched it. What signals the topic is a relation to
    # women, not a mention of them.
    r"喜[欢歡]女|[爱愛]女|和女生|跟女生|女生在一起|"
    r"女友|女朋友|情[侣侶]|彩虹|同性|[两兩][个個]女|姬[圈吧]|拉圈|"
    r"lgbt|[恋戀]爱|老婆|媳[妇婦]|伴[侣侶]|[结結]婚|[监監][护護]",
    re.IGNORECASE,
)

#: Male-only terms, admitted only beside a female marker.
MALE_ONLY = re.compile(r"男同志|男同(?![学學事])|男男|gay\b|bl\b|耽美", re.IGNORECASE)
FEMALE = re.compile(r"女|les\b|lesbian|wlw|百合|拉拉", re.IGNORECASE)

#: Cooking and horticulture. 百合 is the lily and an ingredient, and
#: 女同志 also reads as "female comrades" in a recipe addressed to them
#: ("女同志一定要学会的十种营养蒸菜"), so both are gated on this.
FOOD = re.compile(
    r"[炒煮炖燉蒸煎焖燜拌]|食[谱譜]|菜[谱譜]|做法|[汤湯羹粥]|[莲蓮]子|"
    r"[种種][植]|盆栽|花[语語]|[鲜鮮]花|插花|[虾蝦][仁]|西芹|[药藥]膳|"
    r"[润潤]肺|食材|[营營][养養]|甜品|[红紅]豆沙|[陈陳]皮|花束|花店",
    re.IGNORECASE,
)
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
    # Divination and fortune-telling, a whole genre that uses 女同志 to
    # mean "female client". Hard rather than soft because the case that
    # prompted it carried a topic term and still had to go.
    # Japanese. 百合 is the Japanese word for the same genre, so a
    # search for it returns Japanese yuri content matching the topic
    # term perfectly -- a hundred rows of Vtubers, anime and 百合ヶ浜
    # in one run. Kana is the reliable separator: Chinese uses none.
    ("japanese", r"[\u3040-\u309f\u30a0-\u30ff]"),
    ("divination", r"紫微|斗[数數]|命[盘盤]|八字|塔[罗羅]|占卜|六爻|奇[门門]|"
                   r"[风風]水|生肖|[面手][相]|星座運勢|星座运势|[算批]命|"
                   r"[开開]運|改運|改运"),
    # Scripted fiction: short dramas, novels, audio dramas, comics,
    # edits. Hard, not soft, because 百合短剧 carries a topic term and
    # is still fiction -- and for this study fiction has no author who
    # can be interviewed about why their own video disappeared. `GL`
    # and `girls love` moved here from the topic terms for the same
    # reason: they label a genre, not a person.
    ("fiction", r"短[剧劇]|小[说說]|[广廣]播[剧劇]|有[声聲][书書]|[漫画畫]{2}|[条條]漫|"
                r"[动動]漫|番外|[连連][载載]|完[结結]|全集|合集|"
                r"\bgl\b|girls?\s*love|bg[文向]|甜[宠寵]|[宠寵]文|"
                r"虐[恋戀]|追妻|重生|穿[书書越]|[总總]裁|替身|豪[门門]|"
                r"第\d+集|ep\s*\d+|[剧劇]情|演[绎繹]|混剪|解[说說]|"
                r"女主|男主|男二|女二|原著"),
    # Games, toys and children's media, which is where 拉拉 turns up as
    # a character or a brand: 拉拉公主, 拉拉管玩具, NPC walkthroughs.
    ("games and toys", r"玩具|公主|npc|[游遊][戏戲]|攻略|[联聯]机|沙盒|"
                       r"我的世界|迷你世界|[动動][画畫]片|[儿兒]歌|[积積]木|"
                       r"[盲]盒|开箱|[开開]箱|保安[队隊][长長]|小院"),
)

#: Exclusions an on-topic reading overrides -- the keyword matched
#: incidental rather than the topic.
SOFT: tuple[tuple[str, str], ...] = (
    # 女同 inside an ordinary word about school or work.
    ("not about the topic", r"女同桌|女同[学學]|女同事|女同胞|女同僚"),
    # 拉拉 inside a product or brand name.
    ("unrelated product", r"拉拉[裤褲]|[货貨]拉拉|[巴芭]拉拉|拉拉[队隊]|拉拉操|"
                          r"拉拉手|沙拉拉"),
    # Celebrity gossip. Soft, because gossip about a lesbian public
    # figure is on topic and will carry a term of its own.
    ("gossip", r"八卦|吃瓜|爆料|[黑料]料"),
)

#: Every reason hides the row: the requirement is Chinese-language WLW
#: content, so anything that fails it is out of scope by definition.
#: Hidden, not deleted -- `?show=all` lists them with the reason, and
#: `app/views.py` keeps hand-collected rows visible regardless.
HIDDEN = frozenset(
    {
        "advertising",
        "ai generated",
        "divination",
        "japanese",
        "fiction",
        "games and toys",
        "unrelated product",
        "not about the topic",
        "gossip",
        "not wlw",
        "not in chinese",
        "no topic term",
        "no text",
    }
)

_HARD = tuple((reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in HARD)
_SOFT = tuple((reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in SOFT)


def classify(*parts: object) -> str | None:
    """None when the text is Chinese-language WLW content, else why not.

    Takes the title and description together, since either can carry
    the signal. The order is deliberate: a hard exclusion wins over
    everything, the language requirement is checked before any
    Latin-script topic term so "les" in a Spanish sentence cannot
    qualify, and a topic term is required last.

    A term qualifies either on its own (`ALONE`) or as an ambiguous
    term confirmed by a second signal (`AMBIGUOUS` plus `COMPANION`).
    That two-signal rule replaced a growing blocklist: 拉拉 and 女同 are
    fragments of too many ordinary words for naming the collisions ever
    to finish, and in a real run every genuinely relevant row carried a
    second marker while not one of the collisions did.
    """
    text = "\n".join(str(part) for part in parts if part)
    if not text.strip():
        return "no text"

    for reason, pattern in _HARD:
        if pattern.search(text):
            return reason

    # Chinese, and not Japanese wearing the same characters.
    if not _CJK.search(text) or _KANA.search(text):
        return "not in chinese"

    # 百合 is a lily and an ingredient; 女同志 also reads as "female
    # comrades" in a recipe addressed to them. Neither counts here.
    food = bool(FOOD.search(text))
    on_topic = False
    if not food:
        on_topic = bool(ALONE.search(text)) or (
            bool(AMBIGUOUS.search(text)) and bool(COMPANION.search(text))
        )

    for reason, pattern in _SOFT:
        if pattern.search(text) and not on_topic:
            return reason

    if not on_topic:
        return "no topic term"

    # Male-only content that reached here through a shared term.
    if MALE_ONLY.search(text) and not FEMALE.search(text):
        return "not wlw"
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


def explain(text: str) -> dict[str, object]:
    """Why one piece of text is in or out. Touches no database.

    The rules decide what is in the corpus, so there has to be a way
    to point them at a caption and see the answer and the reason
    together, without collecting anything.
    """
    reason = classify(text)
    return {
        "verdict": "in scope" if reason is None else f"excluded: {reason}",
        "hidden": reason in HIDDEN,
        "chinese": bool(_CJK.search(text)) and not bool(_KANA.search(text)),
        "alone": sorted({m.group(0) for m in ALONE.finditer(text)}),
        "ambiguous": sorted({m.group(0) for m in AMBIGUOUS.finditer(text)}),
        "companion": sorted({m.group(0) for m in COMPANION.finditer(text)}),
        "hard matches": [name for name, p in _HARD if p.search(text)],
        "soft matches": [name for name, p in _SOFT if p.search(text)],
    }


def by_keyword(session) -> dict[str, dict[str, int]]:
    """Cross-tabulate which keyword produced which outcome.

    The overall tally says how much of a run was noise; this says which
    search term produced it. Those are different questions, and only
    the second one tells you what to change: a term returning 90%
    off-topic results is spending quota on rows the filter then
    removes, while a term returning few but clean results is cheap.

    Read from `feed`, which names every keyword that surfaced a video,
    so a video found by two terms counts for both.
    """
    from sqlalchemy import select

    from .parsers import PLATFORM_TABLES

    table: dict[str, dict[str, int]] = {}
    for model, _ in PLATFORM_TABLES.values():
        for feed, reason in session.execute(select(model.feed, model.relevance)):
            if not feed or not feed.startswith("search:"):
                continue
            for keyword in feed[len("search:") :].split(","):
                keyword = keyword.strip()
                if not keyword:
                    continue
                row = table.setdefault(keyword, {})
                key = reason or "in scope"
                row[key] = row.get(key, 0) + 1
    return table


def by_parameter(session) -> dict[str, dict[str, int]]:
    """Cross-tabulate outcome against the sampling parameters used.

    `relevanceLanguage` is a hint YouTube may ignore, not a language
    filter, so whether it helps is a measurement rather than something
    to assume. The parameters are stored on every row, which makes the
    comparison available after the fact: rows collected before the hint
    was configured against rows collected after.
    """
    import json

    from sqlalchemy import select

    from .models import CaptureEvent
    from .parsers import PLATFORM_TABLES

    language: dict[int, str] = {}
    for event in session.scalars(select(CaptureEvent)):
        try:
            payload = json.loads(event.payload)
        except (TypeError, ValueError):
            continue
        language[event.id] = payload.get("relevance_language") or "(none set)"

    table: dict[str, dict[str, int]] = {}
    for model, _ in PLATFORM_TABLES.values():
        for capture_id, reason in session.execute(
            select(model.capture_event_id, model.relevance)
        ):
            key = language.get(capture_id)
            if key is None:
                continue
            row = table.setdefault(key, {})
            name = reason or "in scope"
            row[name] = row.get(name, 0) + 1
    return table


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(
        description="Mark which collected rows are Chinese-language WLW content."
    )
    parser.add_argument(
        "--test",
        metavar="TEXT",
        action="append",
        help="classify this text and print why, storing nothing. Repeatable.",
    )
    parser.add_argument(
        "--test-file",
        metavar="PATH",
        help="classify one line of this file at a time",
    )
    parser.add_argument(
        "--by-keyword",
        action="store_true",
        help="show which search term produced which outcome",
    )
    parser.add_argument(
        "--by-param",
        action="store_true",
        help="show whether the relevanceLanguage hint changed the results",
    )
    args = parser.parse_args()

    samples = list(args.test or [])
    if args.test_file:
        with open(args.test_file, encoding="utf-8") as handle:
            samples += [line.strip() for line in handle if line.strip()]

    if samples:
        for text in samples:
            result = explain(text)
            print(f"\n{text[:90]}")
            for name, value in result.items():
                print(f"  {name:14} {value}")
        return

    from .db import SessionLocal, init_db

    init_db()

    if args.by_param:
        with SessionLocal() as session:
            table = by_parameter(session)
        for value, counts in sorted(table.items()):
            total = sum(counts.values())
            kept = counts.get("in scope", 0)
            share = f"{round(100 * kept / total)}%" if total else "-"
            print(f"\nrelevanceLanguage={value}   {total} rows, {kept} in scope ({share})")
            for reason, count in sorted(counts.items(), key=lambda pair: -pair[1]):
                print(f"   {count:5}  {reason}")
        return

    if args.by_keyword:
        with SessionLocal() as session:
            table = by_keyword(session)
        for keyword, counts in sorted(
            table.items(), key=lambda pair: -sum(pair[1].values())
        ):
            total = sum(counts.values())
            kept = counts.get("in scope", 0)
            share = f"{round(100 * kept / total)}%" if total else "-"
            print(f"\n{keyword}   {total} found, {kept} in scope ({share})")
            for reason, count in sorted(counts.items(), key=lambda pair: -pair[1]):
                print(f"   {count:5}  {reason}")
        return

    with SessionLocal() as session:
        tally = remark(session)
        changed = tally.pop("changed", 0)
        total = sum(tally.values())
        for reason, count in sorted(tally.items(), key=lambda pair: -pair[1]):
            share = f"{round(100 * count / total)}%" if total else "-"
            print(f"{count:6}  {share:>5}  {reason}")
        print(f"\n{changed} row(s) re-marked")


if __name__ == "__main__":  # pragma: no cover
    main()
