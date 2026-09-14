"""Job queue against a real Postgres: DATABASE_URL=... pytest -m db"""

import os

import pytest

from tests.conftest import PARAGRAPH

pytestmark = pytest.mark.db


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    from yue2 import db

    try:
        c = db.connect(os.environ["DATABASE_URL"])
    except (KeyError, psycopg.OperationalError):
        pytest.skip("no database")
    db.init_schema(c)
    c.execute("TRUNCATE songs CASCADE")
    yield c
    c.close()


def test_claim_is_exclusive_and_in_order(conn):
    from yue2 import db

    first = db.create_song(conn, PARAGRAPH, "", 3)
    second = db.create_song(conn, PARAGRAPH, "", 3)
    assert str(db.claim(conn, "a")["id"]) == first
    assert str(db.claim(conn, "b")["id"]) == second
    assert db.claim(conn, "c") is None


def test_worker_processes_a_song(conn, settings):
    from dataclasses import replace

    from yue2 import db, storage, worker
    from yue2.models.fake import FakeModels

    settings = replace(settings, database_url=os.environ["DATABASE_URL"])
    song_id = db.create_song(conn, PARAGRAPH, "https://en.wikipedia.org/wiki/Industrial_Revolution", 2)
    song = db.claim(conn, "test")
    worker.process(settings, conn, storage.load(settings), FakeModels(), None, song)
    found = db.get(conn, song_id)
    assert found["status"] == "done", found["error"]
    assert found["events"][0]["step"] == "setup" and found["events"][-1]["step"] == "done"
    assert found["title"].startswith("Industrial Revolution")

    from fastapi.testclient import TestClient

    from yue2.api.app import create_app

    body = TestClient(create_app(settings)).get(f"/api/songs/{song_id}").json()
    done = body["events"][-1]
    assert done["best"]["audio_url"].startswith("/files/songs/")
    assert all(t["audio_url"] for e in body["events"] if e["step"] == "render" for t in e["takes"])
