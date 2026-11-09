"""Spotify login/API helpers that work without a browser or the network."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import feats
import spotify_api

# Trimmed-down pathfinder responses (same shape as the real ones)
ARTIST_UNION = {
    "uri": "spotify:artist:5rL8nsDdA5x4gJpZS40uvc",
    "profile": {"name": "quintasz", "biography": {"text": "bookquintasz&#64;gmail.com"}},
    "onPlatformReputationTrait": {"verification": {"isVerified": True}},
    "stats": {
        "followers": 10000,
        "monthlyListeners": 20736,
        "worldRank": 0,
        "topCities": {"items": [{"city": "Lisbon", "country": "PT", "numberOfListeners": 4941}]},
    },
    "discography": {
        "latest": {"name": "EGO", "type": "SINGLE", "date": {"year": 2026}},
        "topTracks": {"items": [{"track": {"name": "A1", "playcount": "27355"}}]},
        "albums": {"totalCount": 1},
        "singles": {"totalCount": 5},
    },
    "relatedContent": {"relatedArtists": {"items": [{"profile": {"name": "Lutz"}}]}},
}

PLAYLIST_ITEM = {
    "addedAt": {"isoString": "2026-01-13T16:13:49Z"},
    "itemV2": {"data": {
        "__typename": "Track",
        "uri": "spotify:track:1",
        "name": "Nação",
        "playcount": "15114",
        "artists": {"items": [{"profile": {"name": n}} for n in ("GUIMA", "Vilas Boas", "DJ Suprhyme")]},
        "albumOfTrack": {"name": "Nação"},
        "trackDuration": {"totalMilliseconds": 180000},
    }},
}


# ── /api/token responses ──────────────────────────────────────────────────────
def test_token_logged_in():
    kind, data = spotify_api._parse_token_body(json.dumps({"accessToken": "abc", "isAnonymous": False}))
    assert kind == "token" and data["accessToken"] == "abc"


def test_token_anonymous_means_not_logged_in():
    kind, _ = spotify_api._parse_token_body(json.dumps({"accessToken": "abc", "isAnonymous": True}))
    assert kind == "anonymous"


def test_token_error_response():
    body = json.dumps({"error": {"code": 400, "message": "Unauthorized request"}})
    assert spotify_api._parse_token_body(body) == ("error", "Unauthorized request")


def test_token_garbage():
    assert spotify_api._parse_token_body("<html>")[0] == "error"


# ── Artist page ───────────────────────────────────────────────────────────────
def test_summarize_artist():
    artist = spotify_api.summarize_artist(ARTIST_UNION)
    assert artist["name"] == "quintasz"
    assert artist["uri"] == "spotify:artist:5rL8nsDdA5x4gJpZS40uvc"
    assert artist["verified"] is True
    assert artist["monthlyListeners"] == 20736
    assert artist["worldRank"] is None  # 0 means unranked
    assert artist["bio"] == "bookquintasz@gmail.com"  # entity decoded
    assert artist["topCities"][0] == {"city": "Lisbon", "country": "PT", "listeners": 4941}
    assert artist["topTracks"][0]["name"] == "A1" and artist["topTracks"][0]["playcount"] == 27355
    assert artist["latest"]["name"] == "EGO"
    assert "Lutz" in artist["relatedArtists"]


def test_playlist_track():
    track = spotify_api._summarize_track(PLAYLIST_ITEM)
    assert track["name"] == "Nação" and track["artists"] == ["GUIMA", "Vilas Boas", "DJ Suprhyme"]
    assert track["playcount"] == 15114 and track["addedAt"] == "2026-01-13T16:13:49Z"
    assert track["keys"][0] == feats.song_key("GUIMA", "Nação")


def test_track_keys_match_feat_variants_in_the_csv():
    # The CSV has the title with its "(feat. …)"; one key per Spotify artist
    keys = spotify_api.track_keys("Some (feat. Gson)", ["Wet Bed Gang", "Gson"])
    assert feats.song_key("Wet Bed Gang", "Some (feat. Gson)") in keys
    assert feats.song_key("wet bed gang", "SOME") in keys
    assert feats.song_key("Gson", "Some") in keys


def test_plain_text_strips_links():
    bio = 'Ouve <a href="spotify:artist:1">Slow J</a> &amp; mais'
    assert spotify_api._plain_text(bio) == "Ouve Slow J & mais"
    assert spotify_api._plain_text("") is None


def test_norm_ignores_case_accents_and_spaces():
    assert spotify_api._norm("  Beyoncé ") == spotify_api._norm("beyonce")


# ── Local server only answers the reports (file:// → Origin: null) ────────────
@pytest.fixture
def server(monkeypatch):
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), spotify_api.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url, origin=None, method="GET"):
    req = Request(url, method=method)
    if origin:
        req.add_header("Origin", origin)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_status_for_reports(server):
    spotify_api.clear_login()
    status, data = _get(f"{server}/api/status", origin="null")
    assert status == 200 and data["authenticated"] is False


def test_server_refuses_websites(server):
    assert _get(f"{server}/api/status", origin="https://example.com")[0] == 403
    assert _get(f"{server}/api/auth/logout", origin="https://example.com", method="POST")[0] == 403


def test_artist_needs_login(server):
    spotify_api.clear_login()
    status, data = _get(f"{server}/api/artist?name=Slow%20J", origin="null")
    assert status == 401


# ── Persisted queries read from the web player ────────────────────────────────
def _pathfinder_request(operation, sha="a" * 64, variables=None):
    body = {"variables": variables or {}, "operationName": operation,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}}}
    return {"url": spotify_api.PATHFINDER_URL, "postData": json.dumps(body)}


def test_parse_pathfinder_request():
    op, query = spotify_api._parse_pathfinder_request(_pathfinder_request("searchDesktop", variables={"limit": 10}))
    assert op == "searchDesktop" and query == {"hash": "a" * 64, "variables": {"limit": 10}}


def test_parse_pathfinder_request_ignores_other_traffic():
    assert spotify_api._parse_pathfinder_request(_pathfinder_request("fetchPlaylistMetadata")) is None  # not one we use
    assert spotify_api._parse_pathfinder_request(_pathfinder_request("searchDesktop", sha="xyz")) is None
    assert spotify_api._parse_pathfinder_request({"url": "https://open.spotify.com/api/token"}) is None


def test_query_prefers_discovered_hash():
    spotify_api._queries_file.unlink(missing_ok=True)
    assert spotify_api._query("searchDesktop") == spotify_api.DEFAULT_QUERIES["searchDesktop"]
    spotify_api._queries_file.write_text(json.dumps({"searchDesktop": {"hash": "b" * 64, "variables": {"x": 1}}}))
    try:
        assert spotify_api._query("searchDesktop") == ("b" * 64, {"x": 1})
        assert spotify_api._query("profileAttributes") == spotify_api.DEFAULT_QUERIES["profileAttributes"]
    finally:
        spotify_api._queries_file.unlink()
