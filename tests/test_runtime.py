from truman.core import runtime


def test_is_railway_when_env_set(fake_railway):
    assert runtime.is_railway() is True
    assert runtime.is_local() is False


def test_is_local_when_env_unset(fake_local):
    assert runtime.is_railway() is False
    assert runtime.is_local() is True


def test_db_location_railway(fake_railway, monkeypatch):
    monkeypatch.setattr("os.path.isdir", lambda p: p == "/data")
    assert runtime.db_location() == "/data/truman.db"


def test_db_location_local(fake_local, monkeypatch):
    monkeypatch.setattr("os.path.isdir", lambda p: False)
    assert "truman.db" in runtime.db_location()
    assert "/data/" not in runtime.db_location()


def test_runtime_summary_returns_dict(fake_local):
    s = runtime.runtime_summary()
    assert "location" in s
    assert "db_path" in s
    assert "mac_bridge" in s
    assert s["location"] == "local"


def test_mac_bridge_status_offline_when_no_ws(monkeypatch):
    monkeypatch.setattr("truman.voice.orb._mac_ws", None, raising=False)
    assert runtime.mac_bridge_status() == "offline"
