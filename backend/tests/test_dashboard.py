"""The read-only web view."""

_CAPTURE = {
    "platform_package": "com.zhiliaoapp.musically",
    "fingerprint": "tiktok::someuser::hello",
    "captured_at": "2026-09-14T12:00:00Z",
    "payload": {
        "author_handle": "someuser",
        # On topic, so the capture view lists it by default.
        "caption": "拉拉情侣的一天",
        "like_raw": "74.9K",
        "comment_raw": "1,234",
        "feed": "For You",
    },
}


def _capture(client, api_key, payload=None):
    body = {**_CAPTURE, **(payload or {})}
    return client.post(
        "/api/captures/batch",
        json={"device_id": "pixel-7a", "captures": [body]},
        headers={"X-API-Key": api_key},
    )


def test_dashboard_requires_the_admin_key(client):
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard?key=wrong").status_code == 401


def test_dashboard_accepts_the_key_as_a_query_parameter(client):
    response = client.get("/dashboard?key=test-admin-key")
    assert response.status_code == 200
    assert "Capture dashboard" in response.text


def test_dashboard_accepts_the_key_as_a_header(client):
    response = client.get("/dashboard", headers={"X-API-Key": "test-admin-key"})
    assert response.status_code == 200


def test_a_participant_key_does_not_open_the_dashboard(client, api_key):
    assert client.get(f"/dashboard?key={api_key}").status_code == 401


def test_unknown_platform_is_rejected(client):
    assert client.get("/dashboard?key=test-admin-key&platform=weibo").status_code == 404


def test_empty_state_is_shown_rather_than_a_blank_table(client):
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "Nothing captured for this platform yet." in body


def test_captured_posts_appear_with_their_counts(client, api_key):
    """Under the screen-only chip, which is where a linkless row lives.

    The default listing is one row per link -- see
    `views.SHOW_SCREEN_ONLY` for why -- and this post has none.
    """
    _capture(client, api_key)
    body = client.get(
        "/dashboard?key=test-admin-key&platform=tiktok&show=screen only"
    ).text
    assert "someuser" in body
    assert "74.9K" in body          # 74,900 rendered compactly
    assert "1,234" in body
    assert "no link yet" in body    # no video id yet
    assert "approximate" in body    # the abbreviation flag


def test_a_paired_link_is_rendered_as_a_clickable_url(client, api_key):
    _capture(client, api_key)
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@someuser/video/7301234567890123456",
            "shared_at": "2026-09-14T12:01:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert 'href="https://www.tiktok.com/@someuser/video/7301234567890123456"' in body
    assert "linked (exact)" in body or "linked (by time)" in body


def test_an_unresolved_short_link_is_flagged(client, api_key):
    client.post(
        "/api/links/shared",
        json={"raw_text": "复制打开抖音 https://v.douyin.com/iRkQwBt/ 复制"},
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "needs resolving" in body


def test_captions_are_escaped_not_injected(client, api_key):
    """Escaping has to hold on the off-topic rows too.

    A caption of pure markup has no topic term, so it is only listed
    under show=all -- which is exactly where an injection would be
    rendered if escaping were skipped there.
    """
    _capture(
        client,
        api_key,
        {"payload": {**_CAPTURE["payload"], "caption": "<script>alert(1)</script>"}},
    )
    body = client.get(
        "/dashboard?key=test-admin-key&platform=tiktok&show=all"
    ).text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_export_still_accepts_a_header_key(client, api_key):
    _capture(client, api_key)
    response = client.get(
        "/api/export/posts.csv?platform=tiktok", headers={"X-API-Key": "test-admin-key"}
    )
    assert response.status_code == 200
    assert "someuser" in response.text


def test_one_table_holds_both_halves_of_an_observation(client, api_key):
    """A paired link must not also appear as a row of its own.

    The two-table layout made the reader join a post to its link by
    eye; merging them is only an improvement if the link stops being
    listed twice.
    """
    _capture(client, api_key)
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@someuser/video/7301234567890123456",
            "shared_at": "2026-09-14T12:01:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert body.count("7301234567890123456") == 2  # the href and its text
    assert "Shared links" not in body
    # The caption proves it is the post's row that carries the id.
    assert "拉拉情侣的一天" in body


def test_an_unpaired_link_still_gets_a_row(client, api_key):
    """An unpaired link is a video to re-check, so it must stay visible."""
    client.post(
        "/api/links/shared",
        json={"raw_text": "https://www.tiktok.com/t/ZP83TmDmq/"},
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "needs resolving" in body
    assert "Links to resolve" in body
    assert "app.resolve" in body  # the page says how to fix it


def test_publication_time_is_decoded_from_the_video_id(client, api_key):
    """The id is exact to the second; the rendered string is not.

    7301234567890123456 >> 32 is 1699951143 = 2023-11-14 08:39:03 UTC.
    """
    _capture(client, api_key, {"payload": {**_CAPTURE["payload"], "posted_at_raw": "11h ago"}})
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@someuser/video/7301234567890123456",
            "shared_at": "2026-09-14T12:01:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "2023-11-14 03:39" in body
    assert "from id" in body


def test_an_unresolved_link_is_still_clickable(client, api_key):
    """Before resolution the short URL is all there is, and it opens."""
    client.post(
        "/api/links/shared",
        json={"raw_text": "look at this https://www.tiktok.com/t/ZP83TmDmq/ wow"},
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert 'href="https://www.tiktok.com/t/ZP83TmDmq/"' in body
    # The link itself, not the words "short link": every unresolved
    # row read the same, and the link is what gets pasted elsewhere.
    assert "www.tiktok.com/t/ZP83TmDmq" in body
    assert "short link" not in body


def test_an_unresolved_link_shows_what_the_share_text_said(client, api_key):
    """Dashes across every column, with the answer in the same row.

    The blob Douyin's share sheet produces names the author and
    quotes the caption. A link that never paired to a capture was
    rendering an empty row while that text sat beside it.
    """
    client.post(
        "/api/links/shared",
        json={
            "raw_text": (
                "5.61 复制打开抖音，看看【我爱吃葡萄的作品】"
                "我出现的意义是想告诉你 你不再是一个人 # lwl... "
                "https://v.douyin.com/SXLSe2Qgzl4/ :8p"
            )
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "我爱吃葡萄" in body
    assert "我出现的意义是想告诉你" in body
    assert "v.douyin.com/SXLSe2Qgzl4" in body


def _douyin_link(client, api_key, slug, author, caption, when):
    return client.post(
        "/api/links/shared",
        json={
            "raw_text": (
                f"5.61 复制打开抖音，看看【{author}的作品】{caption} "
                f"https://v.douyin.com/{slug}/ :8p"
            ),
            "shared_at": when,
        },
        headers={"X-API-Key": api_key},
    )


def test_one_post_copied_eighty_times_is_one_row(client, api_key):
    """When the day's results run out the feed stops advancing.

    The loop keeps copying whatever is on screen, so one run put the
    same post in the table eighty times. Every copy is a real
    observation and stays in the database; the reader needs the post
    once, with how often it was seen.
    """
    for number in range(8):
        _douyin_link(
            client,
            api_key,
            f"slug{number}",
            "晒月亮",
            "你冷不冷 饿不饿 想不想我# 姐姐 # lwl",
            f"2026-09-19T17:{20 + number}:00Z",
        )

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert body.count("晒月亮") == 1
    assert "8 seen" in body


def test_two_videos_by_one_author_stay_two_rows(client, api_key):
    """Collapsing by author alone would lose one of them."""
    _douyin_link(
        client, api_key, "one", "珩舟", "#短发 #lwl", "2026-09-19T19:50:00Z"
    )
    _douyin_link(
        client, api_key, "two", "珩舟", "出现# 卡点# lwl", "2026-09-19T19:50:30Z"
    )

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "短发" in body
    assert "卡点" in body


def test_the_screen_and_the_share_text_spell_a_caption_differently(client, api_key):
    """`#短发 #lwl` on screen, `# 短发 # lwl` in the share text.

    Same post. If the spacing kept them apart the table would list
    every post twice for the rest of the study.
    """
    _capture(
        client,
        api_key,
        {
            "platform_package": "com.ss.android.ugc.aweme",
            "fingerprint": "douyin::珩舟::#短发 #lwl",
            "captured_at": "2026-09-19T19:50:00Z",
            "payload": {"author_name": "珩舟", "caption": "#短发 #lwl"},
        },
    )
    _douyin_link(
        client, api_key, "one", "珩舟", "# 短发 # lwl", "2026-09-19T19:50:30Z"
    )

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert body.count("珩舟") == 1
    assert "2 seen" in body


def test_a_display_name_is_not_shown_as_a_handle(client, api_key):
    """On Douyin the handle is the 抖音号, and it is on the profile page.

    The loop never opens one, so the parser stores the display name in
    both columns and the table printed it twice — implying an
    identifier the row does not have.
    """
    _capture(
        client,
        api_key,
        {
            "platform_package": "com.ss.android.ugc.aweme",
            "fingerprint": "douyin::珩舟::#短发",
            "captured_at": "2026-09-19T19:50:00Z",
            "payload": {"author_name": "珩舟", "caption": "#短发 #lwl"},
        },
    )
    # No link on this row, so the screen-only listing is where it
    # appears: the default is one row per link.
    body = client.get(
        "/dashboard?key=test-admin-key&platform=douyin&show=screen only"
    ).text
    assert body.count("珩舟") == 1


def test_the_id_tile_counts_what_the_table_shows(client, api_key):
    """"8% with a video ID" over a page where every row had one.

    The tile counted the post table. With exact-only pairing most ids
    sit on link rows, so it disagreed with the table under it.
    """
    from app.db import SessionLocal
    from app.models import SharedLink

    _douyin_link(
        client, api_key, "one", "珩舟", "#短发 #lwl", "2026-09-19T19:50:00Z"
    )
    with SessionLocal() as session:
        link = session.query(SharedLink).one()
        link.video_id = "7686773732988082810"
        session.commit()

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "1 of 1 collected" in body


def test_a_handle_attached_after_the_fact_is_not_shown(client, api_key):
    """The 抖音号 is on the profile page, and was matched on time.

    It came out the neighbouring author's as often as this one's.
    """
    from app.db import SessionLocal
    from app.models import SharedLink

    _douyin_link(
        client, api_key, "one", "颜小颜", "#lwl #姐1", "2026-09-19T19:50:00Z"
    )
    with SessionLocal() as session:
        link = session.query(SharedLink).one()
        link.author_handle = "🍚"  # the next author along
        session.commit()

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "颜小颜" in body
    assert "🍚" not in body


def test_the_at_sign_does_not_make_two_videos(client, api_key):
    """    恶魔钉（流量回家。）     link only
        @恶魔钉（流量回家。）    no link yet

    One video. The feed's title node renders the name with an @ and
    the share text writes it without; comparing them literally split
    the halves of 51 posts across two rows each.
    """
    _capture(
        client,
        api_key,
        {
            "platform_package": "com.ss.android.ugc.aweme",
            "fingerprint": "douyin::@恶魔钉::嗯嗯嗯",
            "captured_at": "2026-09-19T18:18:00Z",
            "payload": {
                "author_name": "@恶魔钉（流量回家。）",
                "caption": "嗯嗯嗯文艺复兴#lwl #文艺复兴",
                "like_raw": "289",
            },
        },
    )
    _douyin_link(
        client,
        api_key,
        "one",
        "恶魔钉（流量回家。）",
        "嗯嗯嗯文艺复兴# lwl # 文艺复兴",
        "2026-09-19T18:18:30Z",
    )

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "2 seen" in body
    # One video, not two -- the link is still unresolved, so no id yet.
    assert "0 of 1 collected" in body


def test_rows_read_newest_published_first(client, api_key):
    """The table is about when a video went up, not when we saw it."""
    from app.db import SessionLocal
    from app.views import video_rows

    for name, video_id, seen in (
        # Collected in one order, published in another.
        ("older", "7686334741608361451", "2026-09-20T23:40:00Z"),
        ("newer", "7687820515369510629", "2026-09-20T23:30:00Z"),
    ):
        _douyin_link(client, api_key, name, name, f"#lwl {name}", seen)
        with SessionLocal() as session:
            from app.models import SharedLink

            link = (
                session.query(SharedLink)
                .filter(SharedLink.raw_text.contains(name))
                .one()
            )
            link.video_id = video_id
            session.commit()

    with SessionLocal() as session:
        rows = video_rows(session, "douyin", 10)

    assert [row.author_name for row in rows] == ["newer", "older"]


def test_a_video_with_no_publication_time_goes_last(client, api_key):
    """Not sorted among the dated ones on a stand-in.

    Placing it by when it was collected would read as a claim about
    when it was posted.
    """
    from app.db import SessionLocal
    from app.views import video_rows

    # Seen most recently, but nothing says when it was published.
    _douyin_link(client, api_key, "u", "没有时间的", "#lwl", "2026-09-20T23:59:00Z")
    _douyin_link(client, api_key, "d", "有时间的", "#lwl 2", "2026-09-20T23:00:00Z")
    with SessionLocal() as session:
        from app.models import SharedLink

        link = (
            session.query(SharedLink)
            .filter(SharedLink.raw_text.contains("v.douyin.com/d/"))
            .one()
        )
        link.video_id = "7687820515369510629"
        session.commit()

    with SessionLocal() as session:
        rows = video_rows(session, "douyin", 10)

    assert rows[0].author_name == "有时间的"
    assert rows[-1].author_name == "没有时间的"


def test_the_takedown_table_shows_what_the_page_said(client, api_key):
    """The check history knows an id and some timestamps, nothing else.

    So this table had a column of dashes where the author belongs and
    no caption at all -- while `web_videos` already held both, and the
    capture table was showing them. It also dated each row from the
    id, a derivation still unverified on Douyin, when the page had
    handed back the platform's own create_time for the same video.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck, WebAuthor, WebVideo

    video_id = "7687820515369510629"
    with SessionLocal() as session:
        session.add(
            WebVideo(
                video_id=video_id,
                sec_uid="MS4wLjABAAAAQ3os",
                author_name="35",
                caption="再来一次 我不会再与你相恋#wlw",
                posted_on=datetime(2026, 9, 20, 15, 9),
            )
        )
        session.add(
            WebAuthor(sec_uid="MS4wLjABAAAAQ3os", author_handle="70056222078")
        )
        session.add(
            LinkCheck(
                platform="douyin",
                target_kind="video",
                video_id=video_id,
                url=f"https://www.douyin.com/video/{video_id}",
                checked_at=datetime(2026, 9, 21, 23, 34),
                http_status=200,
                evidence="id confirmed",
            )
        )
        session.commit()

    body = client.get(
        "/dashboard/takedowns?platform=douyin&key=test-admin-key"
    ).text
    assert "35" in body
    assert "70056222078" in body
    assert "再来一次" in body
    # The page's own time, not the one decoded from the id.
    assert "2026-09-20 11:09" in body  # 15:09 UTC in America/New_York
    assert "from id?" not in body


def test_the_default_listing_is_one_row_per_link(client, api_key):
    """25 links and 60 screen readings is not 85 videos.

    Listed together they were the same videos twice, with nothing
    saying which half went with which -- and pairing them by time was
    what put one video's handle beside another's caption. So links are
    counted as links, the readings are one chip away with their count,
    and tomorrow's fetch-by-id joins the two without a guess.
    """
    _capture(client, api_key)  # a screen reading, no link
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@elsewhere/video/7301111111111111111",
            "shared_at": "2026-09-14T18:00:00Z",
        },
        headers={"X-API-Key": api_key},
    )

    default = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "7301111111111111111" in default
    assert "someuser" not in default
    # The other half is offered, with its count, rather than dropped.
    assert "screen only, no link" in default

    screen = client.get(
        "/dashboard?key=test-admin-key&platform=tiktok&show=screen only"
    ).text
    assert "someuser" in screen
    assert "7301111111111111111" not in screen


def test_an_unresolved_link_is_not_hidden_by_that_default(client, api_key):
    """It has no id yet and is still a link.

    Hiding it would hide work waiting to be done -- the whole point of
    the "links to resolve" count above the table.
    """
    client.post(
        "/api/links/shared",
        json={"raw_text": "复制打开抖音 https://v.douyin.com/iRkQwBt/ 复制"},
        headers={"X-API-Key": api_key},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "iRkQwBt" in body or "needs resolving" in body


def test_the_page_says_how_much_of_the_corpus_is_one_account(client, api_key):
    """A takedown rate is a rate for whoever is in the sample.

    One TikTok search returned 26 videos from 12 accounts and 15 were
    one account's, which makes the rate substantially that account's.
    Nothing on the page said so, and nobody can work it out from a
    table of 26 rows.
    """
    collected = (
        ("busy", "7301234567890123451"),
        ("busy", "7301234567890123452"),
        ("someone", "7301234567890123453"),
    )
    for handle, video_id in collected:
        client.post(
            "/api/links/shared",
            json={
                "raw_text": f"https://www.tiktok.com/@{handle}/video/{video_id}",
                "shared_at": "2026-09-21T20:15:00Z",
            },
            headers={"X-API-Key": api_key},
        )

    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "Busiest account" in body
    assert "67%" in body        # two of three
    assert "@busy" in body
    assert "3 account(s) in all" not in body  # two accounts, not three rows
    assert "2 account(s) in all" in body


def test_an_account_with_only_a_display_name_is_not_given_an_at_sign(client, api_key):
    """Printing a name as `@name` implies an identifier it has not got.

    The same mistake the handle column was fixed for. The account is
    still counted -- a Douyin row has no 抖音号 until a profile has
    been read, and dropping those would make the spread look wider
    than it is -- it is just not named.
    """
    _capture(
        client,
        api_key,
        {
            "platform_package": "com.ss.android.ugc.aweme",
            "fingerprint": "douyin::珩舟::#短发",
            "captured_at": "2026-09-19T19:50:00Z",
            "payload": {"author_name": "珩舟", "caption": "#短发 #lwl"},
        },
    )
    body = client.get(
        "/dashboard?key=test-admin-key&platform=douyin&show=screen only"
    ).text
    assert "Busiest account" in body
    assert "@珩舟" not in body
    assert "one account" in body


def test_the_filter_reaches_rows_that_never_became_posts(client, api_key):
    """The corpus filter is a SQL condition over the post tables.

    A link that never paired to a post has no row there, so it was
    never subject to it -- invisible while the listing was
    post-shaped, and almost total once the default became one row per
    link. A Douyin rule written to exclude captions like
    LWL出游随拍记录 re-marked none of them: every one was on a link row.
    """
    client.post(
        "/api/links/shared",
        json={
            "raw_text": (
                "【LWL出游随拍记录的作品】LWL出游随拍记录 "
                "https://www.douyin.com/video/7688128736507805041"
            ),
            "shared_at": "2026-09-21T20:15:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/api/links/shared",
        json={
            "raw_text": (
                "【35的作品】再来一次 我不会再与你相恋#wlw "
                "https://www.douyin.com/video/7687820515369510629"
            ),
            "shared_at": "2026-09-21T20:16:00Z",
        },
        headers={"X-API-Key": api_key},
    )

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "再来一次" in body
    assert "LWL出游随拍记录" not in body

    # Hidden, not deleted: it is one click away with its reason.
    excluded = client.get(
        "/dashboard?key=test-admin-key&platform=douyin"
        "&show=no community tag in the caption"
    ).text
    assert "LWL出游随拍记录" in excluded
