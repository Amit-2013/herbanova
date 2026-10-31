def test_app_boots_and_admin_can_log_in(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
