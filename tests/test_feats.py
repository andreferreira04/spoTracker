from collections import Counter

import pytest

import feats


@pytest.mark.parametrize("text, expected", [
    ("Some (feat. Gson)", ("Some", ["Gson"])),
    ("Rich Baby Daddy (feat. Sexyy Red & SZA)", ("Rich Baby Daddy", ["Sexyy Red & SZA"])),
    ("Song (with X)", ("Song", ["X"])),
    ("Song (FEAT. X)", ("Song", ["X"])),
    ("Song (feat X)", ("Song", ["X"])),
    ("Song [with X]", ("Song", ["X"])),
    ("Song [feat. X]", ("Song", ["X"])),
    ("Song (ft. X)", ("Song", ["X"])),
    ("Song feat. X", ("Song", ["X"])),
    ("Song ft. X", ("Song", ["X"])),
    ("Song (feat. X) - Remix", ("Song - Remix", ["X"])),
    ("Song feat. X - Ao Vivo", ("Song - Ao Vivo", ["X"])),
    ("GP DA ZL feat. MC Jhey", ("GP DA ZL", ["MC Jhey"])),
    ("Money In The Grave (Drake ft. Rick Ross)", ("Money In The Grave (Drake)", ["Rick Ross"])),
    # Not feats
    ("Dancing with Myself", ("Dancing with Myself", [])),
    ("Left Behind", ("Left Behind", [])),
    ("Song - Remix", ("Song - Remix", [])),
])
def test_split_feats(text, expected):
    assert feats.split_feats(text) == expected


def test_normalize_ignores_case_accents_and_spacing():
    assert feats.normalize("Não dá  pa parar ") == feats.normalize("NAO DA PA PARAR")


@pytest.mark.parametrize("text, expected", [
    ("Sexyy Red & SZA", ["Sexyy Red", "SZA"]),
    ("A, B & C", ["A", "B", "C"]),
    ("Tyler, The Creator", ["Tyler, The Creator"]),
    ("Tyler, The Creator & Kali Uchis", ["Tyler, The Creator", "Kali Uchis"]),
    ("Zion & Lennox, Bad Bunny", ["Zion & Lennox", "Bad Bunny"]),
    ("A1 x J1", ["A1 x J1"]),
    ("Gunna & ft. Travis Scott", ["Gunna", "Travis Scott"]),
    ("Deejay Telio & Teto feat. Gson", ["Deejay Telio", "Teto", "Gson"]),
    ("Mc Naninha Prod. PZZS", ["Mc Naninha"]),
])
def test_split_artists_keeps_known_artists_whole(text, expected):
    known = {feats.normalize(a) for a in ["Tyler, The Creator", "Zion & Lennox", "SZA"]}
    assert feats.split_artists(text, known) == expected


def test_canonicalize_merges_variants_under_the_most_played_title():
    songs = feats.canonicalize(Counter({
        ("Dillaz", "Querida Já Não Dá"): 3,
        ("Dillaz", "Querida Já Não Dá (feat. Veecious V)"): 5,
        ("Dillaz", "Querida Já Não Dá - Remix"): 1,
        ("SZA", "TINA DANCE"): 1,
        ("SZA", "Tina Dance"): 2,
    }))
    merged = feats.Song("Dillaz", "Querida Já Não Dá (feat. Veecious V)", ("Veecious V",))
    assert songs[("Dillaz", "Querida Já Não Dá")] == merged
    assert songs[("Dillaz", "Querida Já Não Dá (feat. Veecious V)")] == merged
    # A remix is a different track
    assert songs[("Dillaz", "Querida Já Não Dá - Remix")].track == "Querida Já Não Dá - Remix"
    assert songs[("SZA", "TINA DANCE")].track == "Tina Dance"


def test_canonicalize_uses_main_artist_spelling_for_guests():
    songs = feats.canonicalize(Counter({
        ("Drake", "Rich Baby Daddy (feat. Sexyy Red & sza)"): 1,
        ("SZA", "Snooze"): 1,
        ("GP DA ZL feat. MC Jhey", "Tema"): 1,
        ("Kali Uchis", "Song (feat. Tyler, The Creator)"): 1,
        ("Tyler, The Creator", "Earfquake"): 1,
    }))
    assert songs[("Drake", "Rich Baby Daddy (feat. Sexyy Red & sza)")].feats == ("Sexyy Red", "SZA")
    assert songs[("GP DA ZL feat. MC Jhey", "Tema")] == feats.Song("GP DA ZL", "Tema", ("MC Jhey",))
    assert songs[("Kali Uchis", "Song (feat. Tyler, The Creator)")].feats == ("Tyler, The Creator",)
