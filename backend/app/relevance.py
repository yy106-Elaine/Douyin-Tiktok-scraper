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
    # Self-identification, unambiguous even though it contains an
    # otherwise ambiguous term: no tour bus is 是拉拉.
    r"是拉拉|做拉拉|[当當]拉拉|[作]?[为為]拉拉|拉拉身份",
    re.IGNORECASE,
)

#: Keywords too polluted to count on their own, admitted only
#: alongside a second signal from COMPANION. This is the reader's own
#: observation, and it holds: the relevant rows carry several related
#: terms at once, the collisions carry exactly one.
#:
#:   拉拉  names and places -- 拉拉車, 拉拉山, 拉拉秧, 傲拉拉, 朵拉拉,
#:         拉諾拉拉庫, 鬍子拉拉, 烤拉拉, 李拉拉
#:   百合  the lily, in gardening, cooking, Chinese medicine, church
#:         hymns, a Go tournament sponsor (梦百合杯), a dance troupe,
#:         jewellery, and as a person's name (百合才有家)
#:   女同  ordinary words -- 女同学, 女同事, 女同桌 -- and 同 meaning
#:         "with" in Cantonese: 個女同肚入面個B, 呀女同我講
#:
#: 百合 was briefly allowed to count alone, on the reasoning that its
#: polluters all had rules of their own. They did not: FOOD catches
#: recipes but not gardening, hymns, mattresses or people's names, and
#: a review of 47 in-scope rows found 3 correct.
AMBIGUOUS = re.compile(
    r"拉拉|姬|百合|"
    r"(?<![父母仔子兒儿孫孙呀姪侄外])"
    r"女同(?![学學事胞僚桌住框台囚行班窗游遊内內我你他她它佢齡龄款肚])",
    re.IGNORECASE,
)

#: Not enough on its own, but enough to confirm an ambiguous term.
COMPANION = re.compile(
    # Not bare 女生: "港女同內地女生有咩分別" is about girls from two
    # cities, and matched it. What signals the topic is a relation to
    # women, not a mention of them.
    r"喜[欢歡]女|[爱愛]女|和女生|跟女生|女生在一起|追女|"
    r"女友|女朋友|情[侣侶]|彩虹|同性|[两兩][个個]女|姬[圈吧]|拉圈|"
    r"lgbt|[恋戀]爱|老婆|媳[妇婦]|伴[侣侶]|[结結]婚|[监監][护護]|"
    # Genre markers. 百合 beside 短剧, GL or 双女主 is the topic; 百合
    # beside nothing is a flower. This is the overlap pattern in
    # practice, and it is why fiction is in the corpus rather than
    # excluded from it.
    # Not 动漫: any cartoon is animation, and it rescued 巴拉拉小魔仙,
    # a children's show whose title merely contains 拉拉.
    r"短[剧劇]|[漫][画畫]|\bgl\b|girls?\s*love|[双雙]女主|番外|同人|"
    r"[广廣]播[剧劇]|\bcp\b|百合[姬漫]|治愈女同",
    re.IGNORECASE,
)

#: `gl` and `girls love` name the genre on Douyin and YouTube, where
#: they sit beside 短剧, 双女主 and 百合姬. On TikTok they are simply
#: how an English caption says "wlw": `#shaorehushuo #wlw #gl #couple
#: #chinese` is a real couple's translated vlog, posted by the couple,
#: and the same account's posts were landing in the fiction stratum or
#: not depending on whether that one tag happened to be there. Since
#: the stratum is what separates "no author to interview" from "an
#: author to interview", that mislabel would have removed real people
#: from the interview frame.
GENRE_TAG = re.compile(r"\bgl\b|girls?\s*love", re.IGNORECASE)

#: Scripted fiction: short dramas, novels, audio dramas, comics,
#: edits. Kept in the corpus, not excluded from it -- WLW fiction is
#: Chinese WLW content and its removal is the same event this study
#: measures. It was excluded for a while on the argument that fiction
#: has no author to interview; that argument bears on the interview
#: half of the study, not on what counts as a takedown, and the corpus
#: is the wrong place to enforce it. The label stays so the two can be
#: separated in analysis.
FICTION = re.compile(
    r"短[剧劇]|小[说說]|[广廣]播[剧劇]|有[声聲][书書]|[漫画畫]{2}|[条條]漫|"
    r"[动動]漫|番外|[连連][载載]|完[结結]|全集|合集|"
    r"bg[文向]|甜[宠寵]|[宠寵]文|"
    r"虐[恋戀]|追妻|重生|穿[书書越]|[总總]裁|替身|豪[门門]|"
    r"第\d+集|ep\s*\d+|[剧劇]情|演[绎繹]|混剪|解[说說]|"
    r"女主|男主|男二|女二|原著",
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
    ("japanese", r"(?<![0-9A-Za-z])[\u3040-\u309f\u30a0-\u30ff]"),
    ("divination", r"紫微|斗[数數]|命[盘盤]|八字|塔[罗羅]|占卜|六爻|奇[门門]|"
                   r"[风風]水|生肖|[面手][相]|星座運勢|星座运势|[算批]命|"
                   r"[开開]運|改運|改运"),
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

#: Community tags, written as tags.
#:
#: `#lwl` is a label the poster attached to their own post. A bare
#: `lwl` is a string, and on Douyin it turns up as an account name
#: and inside unrelated titles -- LWL出游随拍记录, LWL回顾经典百听不厌,
#: 威龙LWL6666668888. None of those is about anything this study is
#: measuring, and all of them were in the corpus.
#:
#: This is the same argument that put Douyin on no topic filter at
#: all, taken one step further: the hashtag is the community's own
#: label, so it is evidence, and the loose token is a collision like
#: 货拉拉 matching 拉拉.
TAGGED = re.compile(
    r"[#＃]\s*(?:lwl|wlw|les\b|la\b|百合|拉拉|女同|[萌]?t\b|[纯]?p\b|"
    r"[拉蕾][拉丝]|同性|彩虹|girlslove|gl\b|"
    # An alternative spelling, confirmed against the app by the
    # researcher on 2026-09-23 -- the day `#lwl` filtered to the past
    # week returned nothing and `#wlw` returned four, while this one
    # returned more relevant material than either. Which is the point:
    # the community moves to a tag that is not being governed, and a
    # filter that only knows the well-known tags would have thrown
    # that day's collection away as untagged noise.
    #
    # It reads as an ordinary personal name, so it would be a poor
    # keyword. As a *tag* requirement it is fine: this rule asks only
    # whether the poster labelled the post, and the search is still
    # the filter. A video about someone called 陈乐 that carries the
    # hashtag would pass, and is a collision to watch for in review.
    r"[陈陳][乐樂])",
    re.IGNORECASE,
)

#: The same word, written as two tags. `#l #e` and `#l#e` are how
#: this community spells `les` on Douyin -- confirmed by the
#: researcher against the app, not inferred from the text -- and it
#: turns up beside the ordinary tags (#瓜蛋摇 #l #e #wlw) as well as
#: on its own. A caption carrying only this form was being read as
#: having no community tag at all and excluded.
#:
#: Both halves are required. `#l` alone is a letter and `#e` alone is
#: a letter; only the pair says anything, and asking for the pair is
#: what keeps this from matching every caption with a stray one-
#: character tag in it. Order is not fixed -- #wlw #l #e and #l #e
#: #wlw both occur -- so the two are looked for separately.
_SPLIT = (
    re.compile(r"[#＃]\s*l(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"[#＃]\s*e(?![A-Za-z0-9])", re.IGNORECASE),
)


def tagged(text: str) -> bool:
    """Whether the caption carries a community tag in any spelling."""
    if TAGGED.search(text):
        return True
    return all(pattern.search(text) for pattern in _SPLIT)


#: Kept for `--test` and for reading old exclusions back. The rule
#: below no longer asks whether a loose token is present, only
#: whether a tag is: a caption reached by a hashtag search and
#: carrying no hashtag got there by matching something else, and on
#: this corpus that something else was the poster's display name.
#:
#: Bounded by ASCII letters rather than by `\b`, which does not
#: exist between `LWL` and `出`: Python counts CJK as word
#: characters, so `\blwl\b` matched none of LWL出游随拍记录,
#: LWL回顾经典 or 威龙LWL6666668888.
LOOSE_TAG = re.compile(r"(?<![A-Za-z])(?:lwl|wlw|les)(?![A-Za-z])", re.IGNORECASE)

#: A Chinese element in the caption, for the TikTok policy.
#:
#: The search term names the population, but the results do not obey
#: it: `Chinese lesbian` returns `#butchfemme #femme4butch
#: #lesbiansoftiktok`, which is lesbian content with nothing Chinese
#: about it. That is a real video and the wrong population -- this
#: study is of Chinese WLW content, and a takedown rate computed over
#: whatever else the recommender attached to the query is a rate for
#: a different thing.
#:
#: Chinese characters count (kana is a HARD exclusion, so Japanese
#: cannot pass here), as do the English words a diaspora creator
#: actually writes. Deliberately *not* `asian`: it names a population
#: several times larger, and admitting it would quietly restore the
#: drift this rule exists to stop.
CHINESE_MARK = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|"
    r"chines[ae]?s?|chinoises?|china|mandarin|cantonese|"
    r"[cC]-?drama|"
    r"[华華]人|中[国國]|中文|[国國][语語]",
    re.IGNORECASE,
)

#: A WLW element, for the same policy. Wider than `ALONE` because an
#: English caption says it differently -- `wlw`, `lwl`, `sapphic`,
#: `gl` -- and narrower than "anything queer": `lgbt` and `queer`
#: alone cover gay men, trans and bi content, which are neighbouring
#: populations and not this one. They still count when something
#: else on this list is present, which is the ordinary case.
WLW_MARK = re.compile(
    r"l[eé]sb|sapphic|wlw|lwl|girls?\s*love|\bgl\b|\bles\b|"
    r"[女]同|拉拉|百合|女女|蕾[丝絲][边邊]|同性[恋戀]|"
    r"wlwtiktok|femme4femme|butch|femme",
    re.IGNORECASE,
)

#: Why such a row is out.
NO_CHINESE_MARK = "nothing chinese in the caption"
NO_WLW_MARK = "no wlw term in the caption"

#: Why such a row is out.
UNTAGGED = "no community tag in the caption"

#: Every reason hides the row: the requirement is Chinese-language WLW
#: content, so anything that fails it is out of scope by definition.
#: Hidden, not deleted -- `?show=all` lists them with the reason, and
#: `app/views.py` keeps hand-collected rows visible regardless.
#: The label [FICTION] assigns, as it is stored. Named because the
#: dashboard and the survival analysis read the corpus as two strata
#: and this is what divides them: the AI-produced 百合短剧 channels
#: post episode after episode, have no author to interview about a
#: takedown, and answer to different incentives from a person posting
#: their own life. One rate over both explains neither.
FICTION_STRATUM = "fiction"

HIDDEN = frozenset(
    {
        "advertising",
        "ai generated",
        "divination",
        "japanese",
        "games and toys",
        "unrelated product",
        "not about the topic",
        "gossip",
        "not wlw",
        "not in chinese",
        "no topic term",
        "no text",
        UNTAGGED,
        NO_CHINESE_MARK,
        NO_WLW_MARK,
    }
)

_HARD = tuple((reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in HARD)
_SOFT = tuple((reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in SOFT)


def classify(*parts: object, policy: str = "full") -> str | None:
    """None when the text is in scope under [policy], else why not.

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

    [policy] says how much of that to apply, because the platforms are
    sampled differently -- see `FILTER_POLICY`. "full" is the above.
    "language" drops exactly one rule -- that the text must carry a
    topic term -- for a platform whose search already did the topic
    work but which serves other languages. "search" drops the language
    rule as well, for a search term that names the population itself.
    "none" is for a platform where the search is the whole filter and
    the app is mainland-only.
    """
    text = "\n".join(str(part) for part in parts if part)

    # The TikTok policy is the "search" policy plus two requirements
    # on the caption, checked at the end. Everything in between --
    # the hard exclusions, the kana rule, the collision rules -- is
    # shared, so it is expressed as a variant of "search" rather
    # than as a second path through this function.
    marks_required = policy == "chinese-wlw"
    if marks_required:
        policy = "search"

    if policy == "tags":
        # Douyin, and strictly. The sample is drawn by searching the
        # community's hashtags, so the tag in the caption is the
        # evidence that this post is one of theirs. A row that came
        # back from a #lwl search without a tag in its caption got
        # there by matching something else -- and on this corpus that
        # something else is the poster's display name: accounts
        # called LWL, lwl6依然, ▓ Lwl . ▓, whose captions are
        # 上班容易吗, 出海打鱼, 为什么啊, 延吉海兰台.
        #
        # Nothing about language or topic terms runs here; the search
        # is still the whole filter. What this asks is only whether
        # the poster labelled the post.
        if not text.strip():
            return "no text"
        return None if tagged(text) else UNTAGGED

    if policy == "none":
        return None
    if not text.strip():
        return "no text"

    for reason, pattern in _HARD:
        if pattern.search(text):
            return reason

    # Chinese, and not Japanese wearing the same characters.
    #
    # "search" is exempt, and only "search". On TikTok the terms that
    # work are `Chinese lesbian` and 中国女同 -- the ordinary Chinese
    # terms return every language at once -- and what they surface is
    # Chinese and diaspora creators who caption in English. Requiring
    # Chinese characters there would exclude the sample the search was
    # designed to reach. The Japanese exclusion is not weakened by
    # this: kana is a HARD rule, checked above.
    if policy != "search" and (not _CJK.search(text) or _KANA.search(text)):
        return "not in chinese"

    # 百合 is a lily and an ingredient; 女同志 also reads as "female
    # comrades" in a recipe addressed to them. Neither counts here.
    food = bool(FOOD.search(text))
    unambiguous = bool(ALONE.search(text)) and not food
    confirmed = (
        not food
        and bool(AMBIGUOUS.search(text))
        and bool(COMPANION.search(text))
    )

    # A soft exclusion names a word the keyword hides inside, so only
    # an unambiguous term may override it. A merely confirmed
    # ambiguous term may not: 巴拉拉小魔仙 beside 动漫 was reading as
    # on topic and overriding the very rule written to catch 巴拉拉 --
    # the same shape as 拉拉 once overriding 拉拉裤.
    for reason, pattern in _SOFT:
        if pattern.search(text) and not unambiguous:
            return reason

    # The one rule a hand-searched platform does without. The soft
    # exclusions above still apply, because those are keyword
    # collisions -- a 货拉拉 delivery ad is not made relevant by having
    # been returned for 拉拉 -- and so do the two checks below. What
    # goes is the requirement that the text name the topic at all,
    # which is what a caption of nothing but #lwl cannot do.
    if policy not in ("language", "search") and not (unambiguous or confirmed):
        return "no topic term"

    # Male-only content that reached here through a shared term.
    if MALE_ONLY.search(text) and not FEMALE.search(text):
        return "not wlw"

    # The search names the population; the results do not obey it.
    # `Chinese lesbian` returns `#butchfemme #femme4butch
    # #lesbiansoftiktok` -- real, and a different population. Both
    # halves of the name have to be somewhere in the caption.
    #
    # Last, so that a row failing this is reported as failing this,
    # rather than as whatever earlier rule it also failed. The order
    # is Chinese first because that is the half the search gets wrong.
    if marks_required:
        if not CHINESE_MARK.search(text):
            return NO_CHINESE_MARK
        if not WLW_MARK.search(text):
            return NO_WLW_MARK

    # In the corpus, but labelled: fiction is not excluded, and an
    # analysis that needs real accounts can filter on this.
    if FICTION.search(text):
        return "fiction"
    if not marks_required and GENRE_TAG.search(text):
        return "fiction"
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

    from .models import CaptureEvent, WebVideo
    from .parsers import PLATFORM_TABLES
    from .platforms import filter_policy

    # The caption the video's own page gave, which is the authority
    # and the reason the page is fetched at all. The phone reads what
    # the interface rendered, and the interface truncates: a caption
    # stored as 与女朋友的...展开 was being marked off topic on the half
    # of itself that fitted the screen. The dashboard already
    # preferred this text; the stored column did not, so the two
    # disagreed about which rows were in the corpus -- and the CSV
    # export, which reads the column, exported the wrong set.
    page_caption: dict[str, str] = {
        video_id: caption
        for video_id, caption in session.execute(
            select(WebVideo.video_id, WebVideo.caption).where(
                WebVideo.video_id.isnot(None), WebVideo.caption.isnot(None)
            )
        )
        if caption.strip()
    }

    payloads: dict[int, dict] = {}
    for event in session.scalars(select(CaptureEvent)):
        try:
            payloads[event.id] = json.loads(event.payload)
        except (TypeError, ValueError):
            payloads[event.id] = {}

    tally: dict[str, int] = {}
    changed = 0
    for platform, (model, _) in PLATFORM_TABLES.items():
        policy = filter_policy(platform)
        for post in session.scalars(select(model)):
            # Every row is re-marked, including on an unfiltered
            # platform: a row carrying an exclusion from an earlier
            # policy has to be cleared, or loosening the filter would
            # leave the past hidden and the change would look broken.
            payload = payloads.get(post.capture_event_id, {})
            fuller = page_caption.get(post.video_id) if post.video_id else None
            reason = classify(
                fuller or payload.get("caption") or post.caption,
                payload.get("description"),
                policy=policy,
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
    if reason is None:
        verdict = "in scope"
    elif reason in HIDDEN:
        verdict = f"excluded: {reason}"
    else:
        # A label rather than an exclusion: in the corpus, tagged.
        verdict = f"in scope, labelled {reason}"
    return {
        "verdict": verdict,
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


def sample(session, reason: str | None, limit: int = 25) -> list[tuple[str, str]]:
    """Captions for one outcome, as (platform, caption) pairs.

    The counts say how much each rule caught; only the captions say
    whether it caught the right things. `no topic term` is the bucket
    worth reading first -- it is where a real video lands when the
    rules simply do not recognise how it described itself.
    """
    from sqlalchemy import select

    from .parsers import PLATFORM_TABLES

    out: list[tuple[str, str]] = []
    for platform, (model, _) in PLATFORM_TABLES.items():
        statement = select(model.caption).order_by(model.captured_at.desc())
        statement = statement.where(
            model.relevance.is_(None) if reason in (None, "in scope")
            else model.relevance == reason
        )
        for (caption,) in session.execute(statement.limit(limit)):
            if caption:
                out.append((platform, caption))
    return out[:limit]


def preview(session, platform: str, policy: str) -> list[tuple[str, str | None, str | None, str]]:
    """What a policy change would do, without doing it.

    Returns (video_id, current reason, proposed reason, caption) for
    every distinct video on a platform, so the change can be read
    caption by caption before it is written. A filter is only worth
    trusting once someone has read what it removes, and a tally of
    counts is not reading -- the `#lwl` rule looked right as a number
    and was matching account names.

    Captions come from the page where one has been fetched, because
    that is the fuller text and the authority; the screen reading is
    the fallback.
    """
    from sqlalchemy import select

    from .models import SharedLink, WebVideo
    from .parsers import PLATFORM_TABLES

    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return []
    model, _ = registered

    from_page = {
        video_id: caption
        for video_id, caption in session.execute(
            select(WebVideo.video_id, WebVideo.caption).where(
                WebVideo.platform == platform, WebVideo.caption.isnot(None)
            )
        )
    }

    seen: dict[str, tuple[str | None, str]] = {}
    for video_id, caption, reason in session.execute(
        select(model.video_id, model.caption, model.relevance)
        .where(model.video_id.isnot(None))
        .order_by(model.captured_at)
    ):
        seen.setdefault(video_id, (reason, caption or ""))

    # A link row is a video too, and on TikTok most ids arrive that
    # way; those carry no stored reason yet.
    for (video_id,) in session.execute(
        select(SharedLink.video_id).where(
            SharedLink.platform == platform, SharedLink.video_id.isnot(None)
        )
    ):
        seen.setdefault(video_id, (None, ""))

    out = []
    for video_id, (reason, caption) in seen.items():
        text = from_page.get(video_id) or caption
        out.append((video_id, reason, classify(text, policy=policy), text))
    out.sort(key=lambda row: (row[2] or "", row[0]))
    return out


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
    parser.add_argument(
        "--sample",
        metavar="REASON",
        help='print captions for one outcome, e.g. "no topic term" or "in scope"',
    )
    parser.add_argument(
        "--limit", type=int, default=25, help="how many captions to print"
    )
    parser.add_argument(
        "--preview",
        metavar="PLATFORM",
        help="print what a policy would do to this platform, writing nothing",
    )
    parser.add_argument(
        "--policy",
        default=None,
        help="the policy to preview; defaults to the platform's own",
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

    if args.preview:
        from .platforms import filter_policy

        policy = args.policy or filter_policy(args.preview)
        with SessionLocal() as session:
            rows = preview(session, args.preview, policy)
        kept = [r for r in rows if r[2] not in HIDDEN]
        dropped = [r for r in rows if r[2] in HIDDEN]
        print(f"policy {policy!r} over {len(rows)} {args.preview} video(s): "
              f"{len(kept)} in, {len(dropped)} out\n")
        for video_id, was, now, caption in rows:
            mark = "OUT" if now in HIDDEN else " in"
            change = "" if was == now else f"   (was: {was or 'in scope'})"
            one_line = " ".join((caption or "(no caption)").split())
            print(f"{mark}  {video_id}  {now or 'in scope'}{change}")
            print(f"     {one_line[:160]}")
        return

    if args.sample:
        with SessionLocal() as session:
            rows = sample(session, args.sample, args.limit)
        print(f"{args.sample}: showing {len(rows)}\n")
        for platform, caption in rows:
            print(f"[{platform}] {caption}")
        return

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
