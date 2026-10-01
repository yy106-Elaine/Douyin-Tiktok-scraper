"""Tag vocabularies, matched rather than judged.

Of the three things worth labelling on a caption, two are not
judgements at all. Whether a post carries `#wlw`, whether it carries
`#长发t`, whether it carries `#无不良倾向` -- these are string
matching. Handing them to a language model would cost money, add
run-to-run variation, and make a column that is currently exactly
reproducible into one that has to be reported with an agreement
statistic.

So they live here, as vocabularies read off the corpus. Only the
content category -- what the post is *about* -- needs a reader.

Every list below was extracted from a real dump of 372 in-scope
Douyin captions on 2026-10-01, and the counts in
`docs/prompts/caption-categories.md` are from the same pass. When the
corpus grows, add to these lists rather than rewriting them, and
re-run the counts: a vocabulary that silently changes shape between
two analyses is worse than one that is merely incomplete.
"""
from __future__ import annotations

import re

#: How a post names the community it belongs to.
#:
#: `lwl` is `wlw` written backwards. It is not a typo and not a
#: variant spelling -- it is a separate, established tag, and its
#: existence is itself evidence of avoidance. `split` is the one that
#: matters most: `#l #e` is `le` written as two single-letter tags,
#: and a search for it returns nothing, which is the finding that
#: prompted this whole axis.
WLW_TAGS: tuple[tuple[str, str], ...] = (
    ("wlw", r"#wlw"),
    ("lwl", r"#lwl"),
    ("split", r"#l\s*#\s*e|#e\s*#\s*l|#l\s*#\s*a"),
    ("la", r"#la\b|#lala|#les\b|#拉\b|#拉圈|#拉吧|拉吧"),
    ("le", r"#le\b|#el\b|恋爱记le"),
    ("other_abbr", r"#mls|#lmp|#detw|#s1\b"),
    ("gl", r"#gl\b|#双女主|#百合|#纯爱"),
    ("plain", r"喜欢女的|喜欢女生|喜欢女孩|两个女生|全女|只要女生|"
              r"推给女生|妻妻|我老婆|家妻|女朋友|不直"),
)

#: Role vocabulary, in four layers that must stay separable.
#:
#: **This module records what the author wrote. It asserts no mapping
#: from appearance to role.** An earlier draft counted `#短发` and
#: `#甜妹` as inferred T and P. That is a stereotype, not an
#: observation -- the author wrote neither -- so hairstyle, outfit
#: and prettiness tags are not role vocabulary at all and appear in
#: no list below. If they are wanted later they belong in a field of
#: their own, recorded and uninterpreted.
#:
#: `direct` is a bare role letter. `compound` is a role letter inside
#: a longer tag the author chose (`#长发t`). `pairing` describes a
#: *couple's* configuration rather than one person: `#ttl` and
#: `#ppl` name a relationship between two people, so counting them as
#: one person's role label would be a category error, and it would
#: put a post about a T/T relationship in the same bucket as a post
#: where someone calls herself a T. `relational` carries no role
#: letters at all -- terms of address, and position within a dynamic.
TPH_DIRECT = r"#(?:t|p|h|s|1|0|s1|攻|受)(?![a-z0-9\u4e00-\u9fff])"
TPH_COMPOUND = r"#(?:长发t|短发t|短发p|长发p|高p|低p|萌t|姐t|普信t|姐1|妹1)"
#: A relationship between two people, not a label on one of them.
TPH_PAIRING = r"#(?:ttl|ppl|tpl|ttp)(?![a-z0-9])"
#: Longest form first: `#老婆奴` must not be read as `#老婆`, and
#: `#御姐音` is a sound, not a person.
TPH_RELATIONAL = (
    r"#(?:御姐音|御姐|姐姐|姐感|恋姐|年上|年下|小妈感|妹妹|小妹|"
    r"老婆奴|老婆|我的妻子|妻妻|家妻|媳妇|妻子|小狗|小猫)"
)

#: Statements aimed at the moderation system rather than at a reader.
#: Small in number and large in meaning: the author is pre-emptively
#: declaring compliance, or reporting having been actioned.
#: `重发` is not on its own evidence of anything -- `老图重发` is
#: someone reposting an old photo -- so it counts only next to a word
#: about being actioned.
COMPLIANCE = (
    r"无不良|无诱导|无引导|#不违规|正常穿搭无诱导|"
    r"被屏|限流|解封|打码|违规|审核|"
    r"[屏删限封][^。！？]{0,8}重发"
)

_WLW = tuple((name, re.compile(pattern, re.IGNORECASE))
             for name, pattern in WLW_TAGS)
_DIRECT = re.compile(TPH_DIRECT, re.IGNORECASE)
_COMPOUND = re.compile(TPH_COMPOUND, re.IGNORECASE)
_PAIRING = re.compile(TPH_PAIRING, re.IGNORECASE)
_RELATIONAL = re.compile(TPH_RELATIONAL)
_COMPLIANCE = re.compile(COMPLIANCE)

#: Douyin's share text puts a space after every hash: a caption that
#: reads `#wlw #lwl` on screen arrives as `# wlw # lwl` when it is
#: copied out of the app. Every pattern here is written against the
#: on-screen form, so the text is normalised once before matching
#: rather than every pattern learning about it. Without this, every
#: hand-pasted post read as carrying no tags at all -- and hand-pasted
#: posts are most of the 图文.
_HASH_SPACE = re.compile(r"#\s+")


def normalise(text: str) -> str:
    """Close up the space Douyin's share text puts after each hash."""
    return _HASH_SPACE.sub("#", text)


#: What an author writes into their own account name after being
#: actioned. Not a caption and not a tag: a display name, changed so
#: that the people looking for the account can find it again.
#:
#:   （限流版）  this account is throttled
#:   （新号版）  this is the new account; the old one went
#:   小号 / 二号 / 备用号  a spare, kept against the first being lost
#:
#: It is the strongest statement of moderation in the corpus, because
#: it is not a complaint inside one post -- it is a person
#: restructuring how they are findable, and keeping it there. The
#: phrase is what gets recorded; the name itself never leaves the
#: database.
ACCOUNT_MARKS: tuple[tuple[str, str], ...] = (
    ("throttled", r"限流|限流版|被限"),
    ("replacement", r"新号|重开|重注册|回归版"),
    ("spare", r"小号|二号|备用号|分号"),
    ("banned", r"被封|封号|炸号|号没了"),
)
_ACCOUNT = tuple((name, re.compile(pattern)) for name, pattern in ACCOUNT_MARKS)


def account_marks(name: str | None) -> list[str]:
    """Which moderation events this account name reports, if any."""
    if not name:
        return []
    return [kind for kind, pattern in _ACCOUNT if pattern.search(name)]


#: A caption cut off by the interface's "more" fold. The screen only
#: ever showed this much, so the rest was never collected -- and the
#: truncated string is a different string from the full one, so it
#: survives de-duplication as a second row. Marked rather than
#: dropped: it is a real observation of a real post, and what it is
#: not is a complete caption to classify.
#: Two ways a caption arrives incomplete. On screen the fold leaves a
#: visible "展开"; in copied share text it leaves a bare ellipsis and
#: nothing else, so the only evidence that anything is missing is the
#: three dots at the end.
TRUNCATED = re.compile(r"(?:\.\.\.|…)\s*(?:展开)?\s*$")


def wlw_tags(raw: str) -> list[str]:
    """Which community tags this caption carries. `none` if it has none."""
    text = normalise(raw)
    found = [name for name, pattern in _WLW if pattern.search(text)]
    return found or ["none"]


def tph_tags(raw: str) -> list[str]:
    """Which layers of role vocabulary appear. `absent` if none do."""
    text = normalise(raw)
    found = []
    if _DIRECT.search(text):
        found.append("direct")
    if _COMPOUND.search(text):
        found.append("compound")
    if _PAIRING.search(text):
        found.append("pairing")
    if _RELATIONAL.search(text):
        found.append("relational")
    return found or ["absent"]


def tph_terms(raw: str) -> list[str]:
    """The role words themselves, for growing the vocabulary.

    Case-folded, because `#长发t` and `#长发T` are one tag written
    twice and counting them apart splits the largest role term in the
    corpus into two smaller ones.
    """
    text = normalise(raw)
    found = [m.group(0).lower()
             for pattern in (_COMPOUND, _PAIRING, _DIRECT, _RELATIONAL)
             for m in pattern.finditer(text)]
    return sorted(set(found))


def compliance(raw: str) -> bool:
    """Whether the caption addresses the moderation system."""
    return bool(_COMPLIANCE.search(normalise(raw)))


def truncated(text: str) -> bool:
    """Whether the screen cut this caption off at the fold."""
    return bool(TRUNCATED.search(text))
