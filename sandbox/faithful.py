"""Faithfulness: how much of the source's own wording survives, in order, in the lyrics.

The score is a rule, not a judge. Content words (not filler like "the", "of") are compared in order
with a longest-common-subsequence match, so edits cost what they should:
  dropping filler            free
  contraction / plural       free (light normalization)
  synonym                    one content word dropped + one added
  reordering                 breaks the in-order match
  paraphrase                 many drops and additions
"""

import re

STOPWORDS = set("""
a an the and or but nor so yet for of to in on at by with from into onto upon over under about as
is are was were be been being am do does did have has had having it its it's this that these those
which who whom whose what where when while than then there their they them we us our you your he
him his she her i me my not no also such very can could may might must shall should will would
""".split())

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _number_words(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [_ONES[n // 100], "hundred"] + (_number_words(n % 100) if n % 100 else [])
    if 1100 <= n < 2100 and n % 100:  # years read as "nineteen seventy one"
        return _number_words(n // 100) + _number_words(n % 100)
    if n < 1_000_000:
        return _number_words(n // 1000) + ["thousand"] + (_number_words(n % 1000) if n % 1000 else [])
    return [str(n)]


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokens(text: str) -> list[str]:
    """Lowercase words with digits spelled out; hyphens and slashes split words."""
    out = []
    for raw in re.findall(r"[A-Za-z]+(?:'[a-z]+)?|\d+", text.replace("-", " ").replace("/", " ")):
        if raw.isdigit():
            out += _number_words(int(raw))
        else:
            out.append(raw.lower())
    return out


def content(words: list[str]) -> list[str]:
    return [_stem(w) for w in words if w not in STOPWORDS]


def _lcs_pairs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def score(source: str, lyric_lines: list[str]) -> dict:
    """Kept = share of source content words sung in order; added = lyric content words not from the source."""
    src_words = tokens(source)
    src_content_idx = [i for i, w in enumerate(src_words) if w not in STOPWORDS]
    src_content = [_stem(src_words[i]) for i in src_content_idx]

    lyric_content, owner = [], []
    for line_no, line in enumerate(lyric_lines):
        for w in content(tokens(line)):
            lyric_content.append(w)
            owner.append(line_no)

    pairs = _lcs_pairs(src_content, lyric_content)
    matched_src = {i for i, _ in pairs}
    matched_lyr = {j for _, j in pairs}
    kept = len(pairs) / max(len(src_content), 1)
    precision = len(pairs) / max(len(lyric_content), 1)
    # F2: keeping the source's words matters more than avoiding the odd added word.
    faithfulness = (5 * kept * precision / (4 * precision + kept)) if kept and precision else 0.0

    spans = [None] * len(lyric_lines)  # source word range each lyric line sings, for the karaoke player
    for i, j in pairs:
        word_index = src_content_idx[i]
        line = owner[j]
        lo, hi = spans[line] or (word_index, word_index)
        spans[line] = (min(lo, word_index), max(hi, word_index))

    dropped = [src_words[src_content_idx[i]] for i in range(len(src_content)) if i not in matched_src]
    added = []
    for j, w in enumerate(lyric_content):
        if j not in matched_lyr:
            added.append((owner[j], w))
    return {
        "faithfulness": round(faithfulness, 3),
        "kept": round(kept, 3),
        "no_additions": round(precision, 3),
        "dropped_words": dropped,
        "added_words": [{"line": line + 1, "word": w} for line, w in added],
        "source_spans": spans,
        "source_words": re.findall(r"\S+", source),
    }


def clean_source(text: str) -> str:
    """Remove things nobody should sing: citation markers like [2] or [note 1], and collapse whitespace."""
    text = re.sub(r"\[(?:\d+|[a-z]|note \d+|citation needed)\]", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def display_spans(source: str, spans: list) -> list:
    """Map spans over tokens() indices onto whitespace-separated display words of the source."""
    display = re.findall(r"\S+", source)
    token_owner = []
    for d, word in enumerate(display):
        token_owner += [d] * len(tokens(word))
    return [None if s is None else (token_owner[s[0]], token_owner[s[1]]) for s in spans]
