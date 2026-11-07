"""Featured-artist detection and song merging for the reports.

Only the in-memory data is touched: the CSV keeps what Spotify reported, so the
heuristic can be tuned at any time.

- "Some" and "Some (feat. Gson)", or "TINA DANCE" and "Tina Dance", by the same
  artist are merged into one song, shown under its most played title.
- Remixes, live versions and typos stay separate on purpose.
- Featured artists are split on ", " and " & ", except where the joined text is
  already known as a main artist ("Tyler, The Creator", "Zion & Lennox").
"""
import re
import unicodedata
from collections import Counter, namedtuple

# "(feat. X)", "[with X]", "(ft X)" anywhere, or a bare "feat. X" / "ft. X" up to
# a " - Remix"-style suffix or a closing bracket ("(Drake ft. Rick Ross)").
# A bare "with" is left alone ("Dancing with Myself").
FEAT_RE = re.compile(
    r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^)\]]+?)\s*[)\]]"
    r"|\s+(?:feat\.?|ft\.|featuring)\s+([^)\]]+?)(?=\s+-\s|\s*[)\]]|$)",
    re.IGNORECASE,
)
SEPARATOR_RE = re.compile(r"(\s*,\s*|\s+&\s+)")
# A feat inside a feat: "(with Gunna & ft. Travis Scott)", "(with Teto feat. Gson)"
INNER_FEAT_RE = re.compile(r"\s*[,&]?\s+(?:feat\.?|ft\.?|featuring)\s+", re.IGNORECASE)
# Producer credit after the guests: "ft. Mc Naninha Prod. PZZS"
PRODUCER_RE = re.compile(r"\s+prod\.?\s+.*$", re.IGNORECASE)

Song = namedtuple("Song", "artist track feats")


def normalize(text: str) -> str:
    """Case-, accent- and spacing-insensitive key."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())


def split_feats(text: str) -> tuple[str, list[str]]:
    """Split "Some (feat. Gson)" into ("Some", ["Gson"]). Works on artist fields too."""
    found = []

    def take(match):
        found.append(match.group(1) or match.group(2))
        return ""

    base = " ".join(FEAT_RE.sub(take, text).split())
    return (base or text.strip()), [f.strip() for f in found if f.strip()]


def split_artists(text: str, known: set[str]) -> list[str]:
    """Split "Sexyy Red & SZA" into names, keeping known artists whole.

    Greedy: at each position take the longest run of pieces that is a known
    artist, otherwise a single piece.
    """
    text = PRODUCER_RE.sub("", text)
    inner = INNER_FEAT_RE.split(text)
    if len(inner) > 1:
        return [name for part in inner for name in split_artists(part, known)]
    parts = SEPARATOR_RE.split(text.strip())
    names, seps = parts[0::2], parts[1::2]
    result, i = [], 0
    while i < len(names):
        end = i + 1
        for j in range(len(names), i + 1, -1):
            joined = names[i] + "".join(s + n for s, n in zip(seps[i:j - 1], names[i + 1:j]))
            if normalize(joined) in known:
                end = j
                break
        joined = names[i] + "".join(s + n for s, n in zip(seps[i:end - 1], names[i + 1:end]))
        if joined.strip():
            result.append(joined.strip())
        i = end
    return result


def _most_common(counter: Counter) -> str:
    # Ties go to the spelling seen first, so results don't depend on set ordering.
    return counter.most_common(1)[0][0]


def canonicalize(play_counts: Counter) -> dict[tuple[str, str], Song]:
    """Map each raw (artist, track) pair to its merged Song.

    play_counts counts plays per raw pair; it decides which spelling of an
    artist or title is shown.
    """
    artist_names: dict[str, Counter] = {}   # artist key -> spellings
    titles: dict[tuple, Counter] = {}       # song key -> full titles
    feat_texts: dict[tuple, list] = {}      # song key -> raw feat texts
    parsed = {}

    for (artist, track), plays in play_counts.items():
        main, artist_feats = split_feats(artist)
        base, title_feats = split_feats(track)
        akey = normalize(main)
        skey = (akey, normalize(base))
        parsed[(artist, track)] = skey
        artist_names.setdefault(akey, Counter())[main] += plays
        titles.setdefault(skey, Counter())[track] += plays
        feat_texts.setdefault(skey, []).extend(artist_feats + title_feats)

    display = {key: _most_common(names) for key, names in artist_names.items()}
    known = set(display)

    # Feat names first, so a guest who is never a main artist gets one spelling.
    song_feats: dict[tuple, list[str]] = {}
    feat_names: dict[str, Counter] = {}
    for skey, texts in feat_texts.items():
        keys = []
        for text in texts:
            for name in split_artists(text, known):
                fkey = normalize(name)
                feat_names.setdefault(fkey, Counter())[name] += titles[skey].total()
                if fkey != skey[0] and fkey not in keys:
                    keys.append(fkey)
        song_feats[skey] = keys

    def feat_display(fkey):
        return display.get(fkey) or _most_common(feat_names[fkey])

    songs = {
        skey: Song(display[skey[0]], _most_common(titles[skey]),
                   tuple(feat_display(k) for k in song_feats[skey]))
        for skey in titles
    }
    return {pair: songs[skey] for pair, skey in parsed.items()}
