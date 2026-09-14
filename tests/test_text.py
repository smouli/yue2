from yue2.text import faithful
from yue2.text.syllables import count_text_syllables, lyric_lines, syllable_fit

SOURCE = ("Photosynthesis is a biological process used by many cellular organisms to convert light energy into "
          "chemical energy. In 1971, scientists discovered new pathways.")


def test_faithfulness_rewards_trimming_and_punishes_paraphrase():
    trim = ["Photosynthesis, a biological process", "used by many cellular organisms", "to convert light energy",
            "into chemical energy", "in 1971 scientists discovered new pathways"]
    paraphrase = ["Plants eat the sun", "and make sugar", "scientists learned more"]
    assert faithful.score(SOURCE, trim)["faithfulness"] == 1.0
    assert faithful.score(SOURCE, paraphrase)["faithfulness"] < 0.2


def test_numbers_are_spelled_out_and_citations_removed():
    assert faithful.tokens("1800 and 1971") == ["eighteen", "hundred", "and", "nineteen", "seventy", "one"]
    assert faithful.clean_source("Energy.[2] Light[note 1] here[citation needed].") == "Energy. Light here."


def test_syllable_fit_counts_numbers_and_requires_every_line():
    assert count_text_syllables("in 1971") == 7  # in nine-teen sev-en-ty one
    lyrics = "[Verse]\nSunlight lands upon the leaf\nWater rises from the roots"
    assert lyric_lines(lyrics) == ["Sunlight lands upon the leaf", "Water rises from the roots"]
    assert syllable_fit(lyrics, [7, 7])["syllable_fit"] == 1.0
    assert syllable_fit(lyrics, [7, 7, 7])["syllable_fit"] == 0.0
