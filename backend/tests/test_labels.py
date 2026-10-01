"""The tag vocabularies, and the distinctions they must not collapse."""
from __future__ import annotations

from app.labels import (
    compliance,
    tph_tags,
    tph_terms,
    truncated,
    wlw_tags,
)


def test_a_split_letter_tag_is_recognised_as_one_tag() -> None:
    """`#l #e` is `le` written as two tags, and it is the finding.

    A search for it returns nothing, which is why posts carrying it
    are invisible to the very search that is supposed to find them.
    Matched as its own category because the question is how often
    authors write it this way, not whether the letters are present.
    """
    assert "split" in wlw_tags("#瓜蛋摇 #l #e #wlw")
    assert "split" in wlw_tags("一万次想承诺#lwl#l#e")
    assert "split" in wlw_tags("这个视频我只回复一个女孩#wlw #L #E")
    # A complete `#le` is the other thing, and is not `split`.
    tags = wlw_tags("走不进你心里 那我跳进去可以吗#le#wlw")
    assert "le" in tags and "split" not in tags


def test_lwl_is_its_own_tag_not_a_misspelling() -> None:
    """wlw backwards. A separate established tag, and avoidance itself."""
    assert wlw_tags("#短发 #lwl") == ["lwl"]
    assert set(wlw_tags("#wlw #lwl #忧郁")) == {"wlw", "lwl"}


def test_appearance_is_never_read_as_a_role() -> None:
    """`#短发` is a haircut. It is not a declaration of anything.

    An earlier draft counted it, and `#甜妹`, as inferred T and P.
    That is a stereotype rather than an observation: the author wrote
    neither. Hairstyle and prettiness tags are not role vocabulary
    and do not appear in any layer.
    """
    assert tph_tags("希望想念，可以共鸣 #日常分享 #lwl #短发") == ["absent"]
    assert tph_tags("✊✌️✋#lwl #甜妹修炼") == ["absent"]
    assert tph_tags("右滑看我变中性#wlw#中性风 #ootd") == ["absent"]
    assert tph_tags("你的黑长直已上线#lwl") == ["absent"]


def test_a_declared_role_is_recorded_verbatim() -> None:
    assert tph_tags("#wlw #长发t #短发p 喜欢第一张") == ["compound"]
    assert tph_terms("#wlw #长发t #短发p") == ["#短发p", "#长发t"]


def test_a_pairing_tag_is_not_one_persons_role() -> None:
    """`#ttl` and `#ppl` name a relationship, not a label on someone.

    They say what the couple is, so counting them as a role tag on an
    individual is a category error -- and it would also put every
    post about a T/T relationship into the same bucket as a post
    where one person calls herself a T.
    """
    assert tph_tags("#wlw #长发t #ttl 太帅了小王大人") == ["compound", "pairing"]
    assert tph_tags("和爱人💞。#wlw #青春校园装扮 #ppl") == ["pairing"]
    # ...and they are no longer counted as a community abbreviation.
    assert "other_abbr" not in wlw_tags("和爱人💞。#wlw #ppl")


def test_a_term_of_address_is_its_own_layer() -> None:
    """姐姐, 妹妹, 小狗 -- position in a dynamic, with no role letter.

    Recorded as what it is. No claim is made that any of them maps
    onto T, P or H.
    """
    assert tph_tags("你冷不冷 饿不饿 想不想我#姐姐 #lwl") == ["relational"]
    assert tph_tags("我只要独属于我的#wlw#妹妹") == ["relational"]
    assert tph_terms("我的妻子很可爱 #情侣#wlw#老婆奴") == ["#老婆奴"]
    # Tags only, deliberately. "跟老婆在一起307天了" says the same
    # thing in a sentence, but matching free text would drag in every
    # use of the word; widening this is a decision to take with the
    # corpus in hand, not a default.
    assert tph_tags("#wlw 跟老婆在一起307天了#ppl") == ["pairing"]


def test_a_bare_letter_tag_is_direct() -> None:
    assert tph_tags("呼。#lwl#t#三年变化") == ["direct"]
    assert tph_tags("眼泪不听我的 #家教 #t #s #wlw") == ["direct"]
    # ...but a letter inside an ordinary word is not a role tag.
    assert tph_tags("#提车记") == ["absent"]
    assert tph_tags("#手势舞 #wlw") == ["absent"]


def test_a_caption_with_no_role_vocabulary_says_so() -> None:
    assert tph_tags("可是我想念你的时候 你又在哪里#wlw") == ["absent"]
    assert tph_terms("可是我想念你的时候 你又在哪里#wlw") == []


def test_compliance_catches_both_directions() -> None:
    """Declaring innocence in advance, and reporting having been hit."""
    assert compliance("Ready go！#lwl #正常穿搭无诱导行为")
    assert compliance("10年而已#lwl #09 #无不良倾向")
    assert compliance("该叫我什么？被屏了重发。#长发t #wlw")
    assert compliance("🌈 #l#e#lwl OK我直接就是解封了好吧")
    assert not compliance("可是我想念你的时候 你又在哪里#wlw")


def test_a_caption_cut_off_at_the_fold_is_marked() -> None:
    """The screen showed this much, so this much was collected.

    It survives de-duplication as a second row beside its own full
    version, and it is not a complete caption to classify. Marked,
    never dropped: it is a real observation of a real post.
    """
    assert truncated("为了和喜欢的人在一起 我放弃了亚洲第一校 现在社会... 展开")
    assert not truncated("为了和喜欢的人在一起 我放弃了亚洲第一校")


def test_a_caption_with_no_community_tag_at_all() -> None:
    assert wlw_tags("出海打鱼") == ["none"]
    assert wlw_tags("抓紧你的手 走过我的朝朝暮暮") == ["none"]
