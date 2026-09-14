import pytest

from tests.conftest import PARAGRAPH
from yue2 import loop, melody, writer
from yue2.models.fake import FakeModels
from yue2.storage import LocalStorage
from yue2.text.syllables import lyric_lines


def test_melody_profile_phrases(settings):
    profile = melody.load_profile(settings.melody_dir)
    singable = [s.phrases for s in profile["sections"] if s.name in melody.SINGABLE]
    assert singable[:2] == [[7, 7, 7, 7], [7, 8, 13]]
    assert melody.capacity(profile) == 386


def test_fake_writer_fills_every_line(settings):
    plan = loop.song_plan(PARAGRAPH, melody.load_profile(settings.melody_dir))
    budget = [n for s in plan["sections"] for n in s["phrases"]]
    assert len(lyric_lines(writer.fake_write(PARAGRAPH, plan["sections"]))) == len(budget)


def test_paragraph_limits(settings):
    profile = melody.load_profile(settings.melody_dir)
    with pytest.raises(loop.ParagraphError):
        loop.song_plan("Too short to sing.", profile)
    with pytest.raises(loop.ParagraphError):
        loop.song_plan(" ".join([PARAGRAPH] * 12), profile)


def test_run_song_end_to_end_with_fake_models(settings):
    events = []
    storage = LocalStorage(settings.storage_dir)
    done = loop.run_song("song-1", PARAGRAPH, settings=settings, models=FakeModels(), storage=storage,
                         emit=events.append, url="https://en.wikipedia.org/wiki/Industrial_Revolution")

    steps = [e["step"] for e in events]
    assert steps[0] == "setup" and steps[-1] == "done" and "render" in steps
    renders = [e for e in events if e["step"] == "render"]
    assert all(len(e["takes"]) == settings.takes for e in renders)
    assert all(storage.exists(t["audio_key"]) for e in renders for t in e["takes"])  # every take is kept
    best = done["best"]
    assert storage.exists(best["audio_key"])
    assert best["faithfulness"] == 1.0
    assert len(best["source_spans"]) == len(best["lines"])
    assert events[0]["topic"].startswith("Industrial Revolution")
