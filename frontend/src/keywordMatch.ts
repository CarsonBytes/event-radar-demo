// Keyword matching, mirroring app/text_match.py so both sides agree on
// what "matches". Plain substring matching (the original approach here)
// falsely matched short terms inside unrelated words -- e.g. interest
// keyword "ai" matched "fair", "hair", and the venue "Kwai Tsing Theatre".
// Tokenizing both sides and comparing whole (lightly-stemmed) tokens fixed
// that for Latin-script terms while still letting singular interest terms
// match pluralized event text -- but the ASCII-only tokenizer also
// silently dropped every CJK character, so a pure-Chinese term like
// "古天樂" tokenized to `[]` and never matched anything, no matter how
// obviously it appeared in an event's text. CJK terms use a substring
// fallback instead: Chinese has no ASCII-style word boundaries to
// tokenize on, and unlike a 2-letter Latin acronym, a multi-character CJK
// name colliding by accident inside unrelated CJK text is vanishingly
// unlikely -- each character carries far more information than a Latin
// letter.

const WORD_RE = /[a-z0-9]+/g
const CJK_RE = /[㐀-鿿]/

export function tokenize(text: string): string[] {
  return text.toLowerCase().match(WORD_RE) ?? []
}

function stem(token: string): string {
  // Naive trailing-"s" strip -- just enough for "concert" to match
  // "concerts" without re-opening the substring-collision problem this
  // replaced.
  if (token.length > 4 && token.endsWith('s') && !token.endsWith('ss')) {
    return token.slice(0, -1)
  }
  return token
}

export function termMatches(term: string, haystackText: string): boolean {
  if (CJK_RE.test(term)) {
    return haystackText.toLowerCase().includes(term.toLowerCase())
  }

  const termTokens = tokenize(term).map(stem)
  if (termTokens.length === 0) return false
  const stemmedHaystack = tokenize(haystackText).map(stem)
  const n = termTokens.length
  outer: for (let i = 0; i <= stemmedHaystack.length - n; i++) {
    for (let j = 0; j < n; j++) {
      if (stemmedHaystack[i + j] !== termTokens[j]) continue outer
    }
    return true
  }
  return false
}

// Two terms that stem to the same token sequence match the exact same
// events (e.g. "book fair" and "book fairs") -- use this to dedupe terms
// that would otherwise show up as separate, functionally-identical
// suggested-keyword chips. CJK terms fall back to their lowercased literal
// form (tokenize() can't stem what it can't tokenize), so two *different*
// CJK terms never collide into the same key just because both are Chinese.
export function canonicalKey(term: string): string {
  if (CJK_RE.test(term)) return term.toLowerCase()
  return tokenize(term).map(stem).join(' ')
}
