"""Web API and the page that uses it: submit a paragraph, watch the loop work, play the song."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from yue2 import db, loop, storage
from yue2.config import Settings
from yue2.text import faithful

STATIC = Path(__file__).parent / "static"


class SongRequest(BaseModel):
    source: str = Field(min_length=1)
    url: str = ""
    takes: int | None = Field(default=None, ge=1, le=4)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = storage.load(settings)
    app = FastAPI(title="yue2", docs_url="/api/docs")

    def conn():
        return db.connect(settings.database_url)

    with conn() as c:
        db.init_schema(c)

    def with_urls(event: dict) -> dict:
        """Swap storage keys for URLs the browser can play (presigned for S3)."""
        event = dict(event)
        if "audio_key" in event:
            event["audio_url"] = store.url(event["audio_key"])
        if isinstance(event.get("takes"), list):  # the setup event's "takes" is a count
            event["takes"] = [{**t, "audio_url": store.url(t["audio_key"])} for t in event["takes"]]
        if event.get("best", {}).get("audio_key"):
            event["best"] = {**event["best"], "audio_url": store.url(event["best"]["audio_key"])}
        return event

    @app.get("/healthz")
    def healthz():
        with conn() as c:
            c.execute("SELECT 1")
        return {"ok": True, "models": settings.models, "storage": settings.storage}

    @app.post("/api/songs", status_code=201)
    def create(request: SongRequest):
        source = faithful.clean_source(request.source)
        words = len(source.split())
        if not loop.MIN_WORDS <= words <= loop.MAX_WORDS:
            raise HTTPException(422, f"Use a paragraph of {loop.MIN_WORDS} to {loop.MAX_WORDS} words (this one has {words}).")
        with conn() as c:
            song_id = db.create_song(c, source, request.url.strip(), request.takes or settings.takes)
        return {"id": song_id}

    @app.get("/api/songs")
    def songs():
        with conn() as c:
            return db.recent(c)

    @app.get("/api/songs/{song_id}")
    def song(song_id: str):
        with conn() as c:
            try:
                found = db.get(c, song_id)
            except Exception:
                found = None
            if not found:
                raise HTTPException(404, "No such song")
            found["events"] = [with_urls(e) for e in found["events"]]
            if found["result"]:
                found["result"] = with_urls(found["result"])
            if found["status"] == "queued":
                found["queue_ahead"] = db.queue_position(c, song_id)
        return found

    @app.get("/api/paragraphs")
    def paragraphs(url: str):
        import trafilatura

        page = trafilatura.fetch_url(url)
        if not page:
            raise HTTPException(422, "Couldn't fetch that page.")
        text = trafilatura.extract(page, include_comments=False, include_tables=False) or ""
        found = [faithful.clean_source(p) for p in text.splitlines() if 35 <= len(p.split()) <= 110]
        return {"url": url, "paragraphs": found[:40]}

    if settings.storage == "local":
        app.mount("/files", StaticFiles(directory=settings.storage_dir), name="files")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
