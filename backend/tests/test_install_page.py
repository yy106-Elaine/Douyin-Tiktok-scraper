"""The setup page a phone lands on when it opens the backend directly."""


def test_install_page_needs_no_key(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Set up the capture app" in response.text


def test_it_offers_the_apk(client):
    body = client.get("/").text
    assert "capture-latest.apk" in body
    assert "Download the APK" in body


def test_it_shows_the_address_the_phone_actually_reached(client):
    body = client.get("/", headers={"Host": "192.168.1.42:8000"}).text
    assert "http://192.168.1.42:8000" in body


def test_it_exposes_no_collected_data(client, api_key):
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "d1",
            "captures": [
                {
                    "platform_package": "com.zhiliaoapp.musically",
                    "fingerprint": "f1",
                    "captured_at": "2026-09-14T12:00:00Z",
                    "payload": {"author_handle": "secretuser", "caption": "private"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    body = client.get("/").text
    assert "secretuser" not in body
    assert "private" not in body
