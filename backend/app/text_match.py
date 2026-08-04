import re

"""Keyword matching, shared by every place that checks whether an interest
term "matches" event text. Plain substring matching (the original
approach) falsely matched short terms inside unrelated words -- e.g.
interest keyword "ai" matched "fair", "hair", and the venue "Kwai Tsing
Theatre". Tokenizing both sides and comparing whole (lightly-stemmed)
tokens fixed that for Latin-script terms while still letting singular
interest terms match pluralized event text -- but the ASCII-only tokenizer
also silently dropped every CJK character, so a pure-Chinese term like
"古天樂" tokenized to `[]` and never matched anything, no matter how
obviously it appeared in an event's text. CJK terms use a substring
fallback instead: Chinese has no ASCII-style word boundaries to tokenize
on, and unlike a 2-letter Latin acronym, a multi-character CJK name
colliding by accident inside unrelated CJK text is vanishingly unlikely --
each character carries far more information than a Latin letter.
"""

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[㐀-鿿]")  # CJK Unified Ideographs + Extension A


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _stem(token: str) -> str:
    # Naive trailing-"s" strip -- just enough for "concert" to match
    # "concerts" without re-opening the substring-collision problem this
    # replaced (it only ever trims from the end, never creates a match out
    # of a word's *interior* the way plain substring matching did).
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def term_matches(term: str, haystack_text: str) -> bool:
    """True if `term` appears in `haystack_text`."""
    if _CJK_RE.search(term):
        return term.lower() in haystack_text.lower()

    term_tokens = [_stem(t) for t in tokenize(term)]
    if not term_tokens:
        return False
    haystack_tokens = [_stem(t) for t in tokenize(haystack_text)]
    n = len(term_tokens)
    return any(
        haystack_tokens[i : i + n] == term_tokens for i in range(len(haystack_tokens) - n + 1)
    )
