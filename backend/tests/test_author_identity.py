"""Handle versus display name, and the additive migration behind it.

A takedown study ends in interviews, so the author has to be findable.
A display name is neither unique nor stable; only the `@handle` is.
Storing them in one column loses that distinction, so they are separate.
"""

from sqlalchemy import inspect, text

from app.db import SessionLocal, engine, init_db
from app.models import TikTokPost

_BASE = {
    "platform_package": "com.zhiliaoapp.musically",
    "captured_at": "2026-09-14T12:00:00Z",
}


def _ingest(client, api_key, payload, fingerprint="fp-1"):
    return client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [{**_BASE, "fingerprint": fingerprint, "payload": payload}],
        },
        headers={"X-API-Key": api_key},
    )


def test_handle_and_display_name_are_stored_separately(client, api_key):
    _ingest(
        client,
        api_key,
        {
            "author_handle": "leinliv",
            "author_name": "lei n liv",
            "caption": "hello world",
        },
    )

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.author_handle == "leinliv"
        assert post.author_name == "lei n liv"


def test_a_display_name_alone_still_stores(client, api_key):
    # The common case: the feed shows only a display name.
    _ingest(client, api_key, {"author_name": "lilly 🤚", "caption": "hello world"})

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.author_handle is None
        assert post.author_name == "lilly 🤚"


def test_both_appear_in_the_dashboard(client, api_key):
    _ingest(
        client,
        api_key,
        {"author_handle": "leinliv", "author_name": "lei n liv", "caption": "hi there"},
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "leinliv" in body
    assert "lei n liv" in body
    assert "@handle" in body


def test_both_appear_in_the_csv_export(client, api_key):
    _ingest(
        client,
        api_key,
        {"author_handle": "leinliv", "author_name": "lei n liv", "caption": "hi there"},
    )
    response = client.get(
        "/api/export/posts.csv?platform=tiktok",
        headers={"X-API-Key": "test-admin-key"},
    )
    header, row = response.text.strip().splitlines()[:2]
    assert "author_handle" in header and "author_name" in header
    assert "leinliv" in row and "lei n liv" in row


def test_init_db_adds_a_column_an_existing_database_lacks(client):
    """The collection in progress must survive a new column.

    create_all() only creates missing tables, so without this an added
    column breaks every query against a database that already holds
    data.
    """
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS tiktok_posts"))
        # A table as it looked before author_name existed.
        connection.execute(
            text(
                "CREATE TABLE tiktok_posts ("
                "id INTEGER PRIMARY KEY, capture_event_id INTEGER, "
                "participant_id VARCHAR(64), captured_at DATETIME, "
                "author_handle VARCHAR(255), counts_approximate BOOLEAN)"
            )
        )

    assert "author_name" not in {
        column["name"] for column in inspect(engine).get_columns("tiktok_posts")
    }

    init_db()

    columns = {column["name"] for column in inspect(engine).get_columns("tiktok_posts")}
    assert "author_name" in columns
    assert "video_url" in columns
    assert "author_handle" in columns  # untouched


def test_the_migration_is_idempotent(client):
    init_db()
    init_db()
    columns = {column["name"] for column in inspect(engine).get_columns("tiktok_posts")}
    assert "author_name" in columns


def test_a_relative_publication_time_is_resolved_against_the_capture(client, api_key):
    """"11h ago" is exact once the capture time is known.

    Refusing it would leave a takedown study with no publication time at
    all for recent posts, which are exactly the ones a censorship study
    cares about.
    """
    _ingest(
        client,
        api_key,
        {"author_name": "Sophia Belle", "caption": "hi", "posted_at_raw": "· 11h ago"},
    )

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.posted_at_raw == "11h ago"
        assert post.posted_on is not None
        assert (post.captured_at - post.posted_on).total_seconds() == 11 * 3600


def test_an_absolute_date_is_taken_as_given(client, api_key):
    _ingest(
        client,
        api_key,
        {"author_name": "a", "caption": "hi", "posted_at_raw": "· 2025-05-31"},
    )
    with SessionLocal() as session:
        assert session.query(TikTokPost).one().posted_on.date().isoformat() == "2025-05-31"


def test_a_partial_date_is_still_refused(client, api_key):
    # The year is genuinely missing; inferring it would fabricate the
    # variable the study measures from.
    _ingest(client, api_key, {"author_name": "a", "caption": "hi", "posted_at_raw": "5-31"})
    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.posted_at_raw == "5-31"
        assert post.posted_on is None


def test_a_resolved_link_gives_its_post_the_handle(client, api_key):
    """The handle is what finds the account again, so it must land on the row.

    The feed renders a display name only. Without this the handle sat
    in the links table while the @handle column stayed empty -- the one
    field a follow-up interview cannot do without.
    """
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.zhiliaoapp.musically",
                    "fingerprint": "tiktok::displayonly::hi",
                    "captured_at": "2026-09-14T12:00:00Z",
                    "payload": {"author_name": "h <3", "caption": "hi"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@realaccount/video/7301234567890123456",
            "shared_at": "2026-09-14T12:00:30Z",
        },
        headers={"X-API-Key": api_key},
    )

    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert "realaccount" in body
    csv = client.get(
        "/api/export/posts.csv?platform=tiktok", headers={"X-API-Key": "test-admin-key"}
    ).text
    assert "realaccount" in csv


def test_adopting_a_handle_never_replaces_an_observed_one():
    """Directly pinned, because two layers protect this and only one shows.

    Window pairing already refuses an author mismatch, so the endpoint
    test below would pass even if the guard here were removed.
    """
    from types import SimpleNamespace

    from app.pairing import _adopt_handle

    post = SimpleNamespace(author_handle="seenonscreen")
    _adopt_handle(SimpleNamespace(author_handle="@fromlink"), post)
    assert post.author_handle == "seenonscreen"

    empty = SimpleNamespace(author_handle=None)
    _adopt_handle(SimpleNamespace(author_handle="@fromlink"), empty)
    assert empty.author_handle == "fromlink"  # the @ is not stored


def test_a_mismatched_author_is_not_paired_at_all(client, api_key):
    """A directly observed handle outranks one inferred from pairing."""
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.zhiliaoapp.musically",
                    "fingerprint": "tiktok::seen::hi",
                    "captured_at": "2026-09-14T12:00:00Z",
                    "payload": {"author_handle": "seenonscreen", "caption": "hi"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@someoneelse/video/7301234567890123456",
            "shared_at": "2026-09-14T12:00:30Z",
        },
        headers={"X-API-Key": api_key},
    )
    csv = client.get(
        "/api/export/posts.csv?platform=tiktok", headers={"X-API-Key": "test-admin-key"}
    ).text
    assert "seenonscreen" in csv


def test_backfill_repairs_posts_paired_before_handles_were_adopted(client, api_key):
    """An existing database is fixed by re-running app.resolve, not a migration."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import TikTokPost
    from app.pairing import backfill_author_handles

    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.zhiliaoapp.musically",
                    "fingerprint": "tiktok::old::hi",
                    "captured_at": "2026-09-14T12:00:00Z",
                    "payload": {"author_name": "h <3", "caption": "hi"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@realaccount/video/7301234567890123456",
            "shared_at": "2026-09-14T12:00:30Z",
        },
        headers={"X-API-Key": api_key},
    )

    # Put the row back into the state an older pairing left it in.
    with SessionLocal() as session:
        post = session.scalars(select(TikTokPost)).one()
        post.author_handle = None
        session.commit()

        assert backfill_author_handles(session) == 1
        session.expire_all()
        assert session.scalars(select(TikTokPost)).one().author_handle == "realaccount"
        # Idempotent: nothing left to fill.
        assert backfill_author_handles(session) == 0
