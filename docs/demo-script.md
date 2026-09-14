# Demo video voiceover script

Timed to `results/yue2-demo-v4.mp4` (2:38), which is v3 with the 30-second "Under the hood" block spliced in. Read at a relaxed pace; the timings leave room. Stay silent where it
says **(pause)** so the audio clips and the song carry those moments.

## How to record

1. Open the video in QuickTime on one side of the screen, with sound **off** (you'll hear yourself otherwise).
2. QuickTime → File → New Movie Recording. Face centered, even light in front of you, plain background.
3. Start the recording, then **clap once** and press play on the video at the same moment (the clap syncs the tracks).
4. Read along using the cues below. Stop the recording when the video ends.
5. Save as `~/projects/yue2/results/facecam.mov`.

A second take is fine; small timing drift is corrected when compositing.

## Script

**0:00 – 0:11 · Product and question**
> Hi, I'm Sanat. We're building an app to make and remix music. This weekend we asked a simple question: can it sing what you're reading?

**0:11 – 0:14 · The problem**
> Singing real text is hard. Here's our first try on a biology paragraph.

**0:14 – 0:22 · (pause)**: the garbled clip plays.

**0:22 – 0:34 · The loop**
> So we built a loop. It fits the page's own words to the melody, sings three takes, listens back with Whisper, scores every line, and rewrites only the lines it misheard.

**0:34 – 0:52 · Pass by pass**
> Here's a paragraph about the Industrial Revolution. On the first pass, line one came out as nonsense. By pass three, it's heard word for word, and clarity climbs to eighty percent while staying faithful to the text.

**0:52 – 0:55**
> Here's the result.

**0:55 – 1:32 · (pause)**: the song plays with karaoke. The bubble is hidden here.

**1:33 – 1:50 · What we tune**
> Every choice is a trade-off, and the loop measures both sides. Slowing the tempo tripled clarity. And we sing three takes, because the same lyrics can score anywhere from twenty-two to eighty-one percent.

**1:50 – 2:02 · How it learns**
> Across songs, it proposes its own rules. Each one has to win an A/B test on forty drafts from pages it hasn't seen. Only three of eighteen made the cut.

**2:02 – 2:32 · Under the hood** (your face fills the big circle on the left)

*On screen, 2:02 – 2:12: the scoring rubric table. Glance at it as you talk through the three scores.*
> Here's how we score it. Every line gets checked three ways: Whisper tells us whether it was heard clearly, we measure how much of the source's own wording survived in order, and we match syllables to the melody's notes.

*On screen, 2:13: "Dataset so far".*
> So far the loop has written 225 lyric drafts and sung 184 takes, and we scored about 960 more drafts while testing rules. Every one of them is traced in Weave.

*On screen, 2:19: "Next: fine-tuning".*
> Next, we'll fine-tune a small writer on the best of those lyrics and serve it on W&B Inference, so first drafts start close to finished.

**2:32 – 2:38 · Close**
> Everything runs on a marimo molab GPU. Thanks for watching.

## Rubric reference (for questions)

The same table is saved as `docs/rubric.png` for slides and the submission page. Targets are the defaults in
`loop.run_faithful`.

| Score | How it's measured | Target | What the loop does with it |
|---|---|---|---|
| **Heard clearly** | Whisper large-v3 transcribes the sung take; each lyric line is compared to what was heard letter by letter, with numbers spelled out on both sides | song ≥ 90% and every line ≥ 85% | stop when met; lock lines at 85%+; send misheard lines back with what was heard |
| **Faithful to the text** | Content words from the source, matched in order against the lyrics; dropped words and added words both lower it (weighted toward keeping words) | ≥ 85% | stop rewriting text when met together with syllable fit |
| **Syllable fit** | Syllables per line from the CMU pronunciation dictionary vs. notes in that melody phrase, allowing ±1 | ≥ 90% | same; off-budget lines get specific feedback |
| **Melody check** | SheetSage2 re-transcribes the kept take and compares its notes to the original melody | guardrail | reported only; YuE2 holds the melody even when words fail |

- **Best of 3 takes:** average of the song's clarity and its worst line, so one garbled line can't hide behind a good average.
- **Best pass:** heard clearly × faithful to the text.
- **No LLM grades these three scores.** Whisper and SheetSage2 are models, but the scores themselves are computed by code.
