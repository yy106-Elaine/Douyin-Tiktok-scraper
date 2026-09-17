"""The read-only web view."""

_CAPTURE = {
    "platform_package": "com.zhiliaoapp.musically",
    "fingerprint": "tiktok::someuser::hello",
    "captured_at": "2026-09-14T12:00:00Z",
    "payload": {
        "author_handle": "someuser",
        "caption": "hello world",
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
    _capture(client, api_key)
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
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
    _capture(
        client,
        api_key,
        {"payload": {**_CAPTURE["payload"], "caption": "<script>alert(1)</script>"}},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
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
    assert "hello world" in body


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
    assert "2023-11-14 08:39" in body
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
    assert "short link" in body
