"""Who to approach, and what happened to their posts.

The study's point is not the rate. The rate says something was
removed; the people who made those posts are the only ones who can
say what it was like to have it removed, and this is the list of
them -- one row per account, not per post, because an interview is
asked of a person.

An account is on the list when at least one of its posts in the
corpus has been found gone. Reaching it needs the 抖音号: a display
name is shared and changeable, and the profile address is keyed on an
id the person never sees. So every row carries the handle where there
is one, the profile link, and -- where there is not -- the reason,
which is itself a finding. An account whose profile the site will not
serve is usually an account that is itself gone, and that is a
heavier outcome than a post being removed.

The posts stay collapsed under each account. The removed set runs to
hundreds and nobody reads it as a flat list; what a person deciding
who to write to needs first is who, how many of their posts went, and
whether any came back.

Nothing here is a sample. Stratifying by what the posts are *about*
needs the content coding, which has not been run -- see
`stratify_placeholder`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthorPost, WebAuthor, WebVideo
from .platforms import family_members
from .survival import Finding, findings

PROFILE_URL = "https://www.douyin.com/user/{sec_uid}"


@dataclass
class Post:
    """One post of one account, and what became of it."""

    video_id: str
    platform: str
    caption: str | None
    published_at: datetime | None
    first_gone_at: datetime | None
    came_back_at: datetime | None
    lifetime: timedelta | None
    #: Gone at the last check.
    gone: bool
    #: Found gone at some point, whether or not it is back.
    ever_gone: bool

    @property
    def state(self) -> str:
        if self.gone:
            return "已下架 (gone)"
        if self.ever_gone:
            return "下架后恢复 (came back)"
        return "仍在 (up)"


@dataclass
class Candidate:
    """One account worth approaching."""

    sec_uid: str
    handle: str | None
    name: str | None
    posts: list[Post] = field(default_factory=list)
    #: What the profile pass last said, when it could not read it.
    profile_error: str | None = None
    #: Whether a profile reading has been attempted at all.
    read: bool = False

    @property
    def profile_url(self) -> str:
        return PROFILE_URL.format(sec_uid=self.sec_uid)

    @property
    def removed(self) -> int:
        return sum(1 for p in self.posts if p.ever_gone)

    @property
    def still_gone(self) -> int:
        return sum(1 for p in self.posts if p.gone)

    @property
    def came_back(self) -> int:
        return sum(1 for p in self.posts if p.ever_gone and not p.gone)

    @property
    def reachable(self) -> bool:
        return bool(self.handle)

    @property
    def note(self) -> str:
        """Why this account can or cannot be written to.

        The distinction that matters is between "we have not looked"
        and "there is nothing to look at". The second is a result:
        the account itself is gone, and the person is not reachable
        through the platform at all.
        """
        if self.handle:
            if self.came_back and not self.still_gone:
                return "可联系；其帖子下架后又恢复"
            return "可联系 (handle on file)"
        if not self.read:
            return "尚未读取 profile — run app.fetch_authors"
        if self.profile_error:
            return f"读不到 profile：{self.profile_error}（账号多半已注销/封禁）"
        return "profile 读到了但没有抖音号"


def _links(session: Session, platform: str) -> dict[str, set[str]]:
    """Which account posted which video, from every record of it.

    Three sources, because they were written at different times and
    none alone is complete. `author_posts` is the durable one and is
    only as old as itself; a live post still carries its own
    `sec_uid`; and before either existed, a removed post's account was
    saved on the author row as `kept_for_video_id` -- one post per
    account, which is why that one is a fallback and not the source.
    """
    members = set(family_members(platform))
    out: dict[str, set[str]] = {}

    for sec_uid, video_id in session.execute(
        select(AuthorPost.sec_uid, AuthorPost.video_id).where(
            AuthorPost.platform.in_(members)
        )
    ):
        out.setdefault(sec_uid, set()).add(video_id)

    for sec_uid, video_id in session.execute(
        select(WebVideo.sec_uid, WebVideo.video_id).where(
            WebVideo.platform.in_(members), WebVideo.sec_uid.isnot(None)
        )
    ):
        out.setdefault(sec_uid, set()).add(video_id)

    for sec_uid, video_id in session.execute(
        select(WebAuthor.sec_uid, WebAuthor.kept_for_video_id).where(
            WebAuthor.kept_for_video_id.isnot(None)
        )
    ):
        out.setdefault(sec_uid, set()).add(video_id)

    return out


def _post(finding: Finding, row: WebVideo | None) -> Post:
    span = finding.lifetime()
    return Post(
        video_id=finding.video_id,
        platform=finding.platform,
        caption=(row.caption if row is not None else None),
        published_at=finding.published_at,
        first_gone_at=finding.first_gone_ever or finding.first_gone_at,
        came_back_at=finding.came_back_at,
        # The upper bound: from publication to the check that found it
        # gone. The lower bound is in `Finding.lifetime`; one number
        # on a list like this should be the conservative one.
        lifetime=(span[1] if span else None),
        gone=finding.is_gone,
        ever_gone=bool(finding.is_gone or finding.disappearances),
    )


def candidates(session: Session, platform: str = "douyin") -> list[Candidate]:
    """Accounts with at least one post of theirs found gone.

    Sorted by how much of their work went: most removals first, then
    the ones still gone, then by account id so the order is stable
    between runs of the page.
    """
    links = _links(session, platform)
    by_video = {f.video_id: f for f in findings(session, platform)}
    rows = {
        row.video_id: row
        for row in session.scalars(
            select(WebVideo).where(
                WebVideo.platform.in_(set(family_members(platform)))
            )
        )
    }
    authors = {
        author.sec_uid: author
        for author in session.scalars(select(WebAuthor))
    }

    out: list[Candidate] = []
    for sec_uid, video_ids in links.items():
        posts = [
            _post(by_video[video_id], rows.get(video_id))
            for video_id in sorted(video_ids)
            if video_id in by_video
        ]
        if not any(p.ever_gone for p in posts):
            continue
        author = authors.get(sec_uid)
        posts.sort(key=lambda p: (not p.ever_gone, p.first_gone_at or datetime.max))
        out.append(Candidate(
            sec_uid=sec_uid,
            handle=author.author_handle if author else None,
            name=author.author_name if author else None,
            profile_error=author.error if author else None,
            read=bool(author and author.fetched_at and author.http_status is not None),
            posts=posts,
        ))

    out.sort(key=lambda c: (-c.removed, -c.still_gone, c.sec_uid))
    return out


@dataclass
class Frame:
    """The interview frame, counted."""

    accounts: int = 0
    reachable: int = 0
    unreachable: int = 0
    removed_posts: int = 0
    came_back_posts: int = 0


def frame(people: list[Candidate]) -> Frame:
    found = Frame(accounts=len(people))
    for person in people:
        if person.reachable:
            found.reachable += 1
        else:
            found.unreachable += 1
        found.removed_posts += person.removed
        found.came_back_posts += person.came_back
    return found


def stratify_placeholder() -> str:
    """Why there is no sampling here yet.

    Said on the page rather than left to be noticed: a list this
    length invites being worked through from the top, and the top is
    "most posts removed", which is not a sample of anything. The
    sampling frame is meant to be stratified by what the posts are
    about -- affection, daily life, a community tag -- and that needs
    the content coding, which has not been run over the corpus.
    """
    return (
        "No sampling yet. This list is ordered by how many of an "
        "account's posts were removed, which is useful for reading and "
        "is not a sample. The intended frame is stratified by what the "
        "posts are about (affection, daily life, community tags, and "
        "so on) and that needs the content coding, which has not been "
        "run over the corpus."
    )
