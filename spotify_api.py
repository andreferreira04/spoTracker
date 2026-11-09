"""Spotify login and the private web-player API, served to the reports over localhost.

Login (docs/implement-spotify-private-api/get-auth-token.md)
------------------------------------------------------------
We open a Chrome/Edge window on open.spotify.com with its own profile (kept in
the data folder, so the user only logs in once) and watch its network traffic
through the DevTools protocol. When the web player calls
``open.spotify.com/api/token`` we read the response: ``isAnonymous: true`` means
the user still has to log in, otherwise we store the token on disk and close
the window. When the token expires it is refreshed the same way, in a headless
browser that reuses the saved Spotify session.

The persisted-query hashes of the web player's API change from time to time.
After each login, and whenever Spotify answers 412 (outdated hash), a headless
browser opens an artist page and a search and saves the queries the web player
sends (spotify_queries.json); DEFAULT_QUERIES are only the starting values.

Local API (started by the tray app on 127.0.0.1:PORT)
-----------------------------------------------------
GET  /api/status          logged in? token expired? profile confirmed?
POST /api/auth/login      open the Spotify window and wait for the token
GET  /api/auth/state      progress of that login
POST /api/auth/confirm    the user confirmed the profile is theirs
POST /api/auth/logout     forget the token and the browser session
GET  /api/profile         the user's Spotify profile (get-spotify-profile.md)
GET  /api/artist?name=X   an artist's Spotify page (get-artist-profile.md)
GET  /api/playlists       the user's playlists and their tracks (?refresh=1 skips the cache)

The reports are opened from file://, so browsers send ``Origin: null``. Any
other origin is refused, so websites can't use the user's token.
"""

import base64
import html
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import platform_utils as pu

PORT = 47815

TOKEN_URL_MARK = "open.spotify.com/api/token"
PATHFINDER_URL = "https://api-partner.spotify.com/pathfinder/v2/query"

LIKED_SONGS_PAGE = "https://open.spotify.com/collection/tracks"
PLAYLIST_PAGE = 100

# Persisted queries: the web player sends the SHA-256 of a GraphQL query instead
# of the query itself. The hashes are public and the same for everyone, but they
# change when Spotify edits a query (an outdated one answers HTTP 412). Then the
# current ones are read from the web player itself (_discover_queries) and saved
# in the data folder; these are only the starting values.
DEFAULT_QUERIES = {
    "profileAttributes": ("08ffb4730af3746e04a8301396f20875dbbce10c75243803091a9274eacc8ac0", {}),
    "queryArtistOverview": ("eafb1620d783ece118e72fbfede2b0064483e029d3c1aafafa1c2de0e25a89e7", {
        "uri": "", "locale": "", "preReleaseV2": False, "includeMusicVideoPreviews": False,
    }),
    "searchDesktop": ("eef7cc54888d91bdd6802623477873caa3948ae173a0c34fd86827b267e94c03", {
        "searchTerm": "", "offset": 0, "limit": 10, "numberOfTopResults": 5,
        "includeAudiobooks": False, "includeArtistHasConcertsField": False,
        "includePreReleases": False, "includeAlbumPreReleases": False, "includeAuthors": False,
        "includeEpisodeContentRatingsV2": False, "isPrefix": None, "sectionFilters": ["GENERIC"],
    }),
    # The user's library ("Your Library" sidebar), filtered to playlists
    "libraryV3": ("390c78e5b951029bad359785e69b07b536a509c581cbcd0aded5e5067f187455", {
        "order": None, "textFilter": "", "features": ["LIKED_SONGS"], "limit": 50, "offset": 0,
        "flatten": True, "expandedFolders": [], "folderUri": None, "includeFoldersWhenFlattening": False,
        "filters": ["Playlists"],
    }),
    # A playlist page (get-playlist-content.md), also used for Liked Songs (get-liked-songs.md)
    "fetchPlaylist": ("21ea11a6ac75a5f3e01fd365d29c18e0a4a8b7dc09f89bbb5d73910190c6acaf", {
        "uri": "", "offset": 0, "limit": 100, "enableWatchFeedEntrypoint": False,
        "includeEpisodeContentRatingsV2": False,
    }),
}
DISCOVERY_ARTIST_ID = "4gzpq5DPGxSnKTe4SA8HAU"  # Coldplay: any artist page works
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_data_dir = pu.get_data_dir()
_token_file = _data_dir / "spotify_token.json"
_browser_profile = _data_dir / "spotify-browser"
_artist_uri_file = _data_dir / "spotify_artists.json"
_queries_file = _data_dir / "spotify_queries.json"
_playlists_file = _data_dir / "spotify_playlists.json"


class NotAuthenticated(Exception):
    pass


# ── Token storage ─────────────────────────────────────────────────────────────
_store_lock = threading.Lock()


def _read_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def load_token():
    with _store_lock:
        return _read_json(_token_file, None)


def save_token(data):
    with _store_lock:
        _token_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_token(**fields):
    with _store_lock:
        data = _read_json(_token_file, None)
        if data:
            data.update(fields)
            _token_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_login():
    """Forget the token and the browser's Spotify session (so another account can log in)."""
    with _store_lock:
        _token_file.unlink(missing_ok=True)
        _artist_cache.clear()
    shutil.rmtree(_browser_profile, ignore_errors=True)


def _is_fresh(token):
    expires = token.get("accessTokenExpirationTimestampMs", 0)
    return expires > time.time() * 1000 + 60_000  # at least one minute left


# ── Browser login through the DevTools protocol ───────────────────────────────
class LoginState:
    """Progress of a login, polled by the report page."""

    TERMINAL = {"success", "error", "cancelled", "timeout"}

    def __init__(self):
        self._lock = threading.Lock()
        self.status = "idle"
        self.message = ""

    def set(self, status, message=""):
        with self._lock:
            self.status, self.message = status, message

    def snapshot(self):
        with self._lock:
            return {"status": self.status, "message": self.message}

    @property
    def running(self):
        return self.status not in self.TERMINAL | {"idle"}


_login_state = LoginState()
_login_lock = threading.Lock()  # one browser at a time (interactive or refresh)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_devtools(port, proc, timeout=15):
    """websocket URL of the browser once its DevTools endpoint is up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "The browser closed right away. If a SpoTracker Spotify window is "
                "already open, close it and try again."
            )
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                return json.loads(resp.read())["webSocketDebuggerUrl"]
        except (URLError, OSError, ValueError, KeyError):
            time.sleep(0.25)
    raise RuntimeError("The browser did not start in time.")


def _parse_token_body(body):
    """Classify an /api/token response: ("token", data), ("anonymous", data) or ("error", message)."""
    try:
        data = json.loads(body)
    except ValueError:
        return "error", "Spotify returned an unreadable token response."
    if "error" in data:
        err = data["error"]
        return "error", err.get("message", str(err)) if isinstance(err, dict) else str(err)
    if not data.get("accessToken"):
        return "error", "Spotify's token response had no access token."
    if data.get("isAnonymous", True):
        return "anonymous", data
    return "token", data


class _Browser:
    """A Chromium window (or headless browser) on the SpoTracker profile, driven over DevTools.

    Every tab is attached automatically, including ones opened later (e.g. a
    login popup), and new tabs stay paused until their network is watched.
    """

    def __init__(self, headless):
        import websocket  # websocket-client
        self._ws_errors = websocket

        exe = pu.find_chromium_browser()
        if not exe:
            raise RuntimeError("Spotify login needs Google Chrome, Microsoft Edge, Brave or Chromium installed.")
        debug_port = _free_port()
        _browser_profile.mkdir(parents=True, exist_ok=True)
        args = [
            exe,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={_browser_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1100,800",
        ]
        if headless:
            args.append("--headless=new")
        args.append("about:blank")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self._next_id = 0
        self.page = None  # session id of the first tab
        try:
            # Chrome rejects DevTools websockets that carry an Origin header unless
            # --remote-allow-origins is set, so the header is suppressed instead.
            self.ws = websocket.create_connection(_wait_for_devtools(debug_port, self.proc, timeout=15),
                                                  timeout=1, suppress_origin=True)
            self.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
        except Exception:
            self.close()
            raise

    def send(self, method, params=None, session=None):
        self._next_id += 1
        msg = {"id": self._next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        return self._next_id

    def navigate(self, url):
        self.send("Page.navigate", {"url": url}, session=self.page)

    def messages(self, deadline):
        """DevTools messages until the deadline. Stops early (returns) if the browser goes away."""
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return
            try:
                msg = json.loads(self.ws.recv())
            except self._ws_errors.WebSocketTimeoutException:
                yield None  # lets callers act on time passing
                continue
            except (self._ws_errors.WebSocketConnectionClosedException, OSError):
                return
            if msg.get("method") == "Target.attachedToTarget" and msg["params"]["targetInfo"]["type"] == "page":
                child = msg["params"]["sessionId"]
                self.send("Network.enable", session=child)
                self.send("Runtime.runIfWaitingForDebugger", session=child)
                if self.page is None:
                    self.page = child
            yield msg

    def close(self):
        if self.ws is not None:
            try:
                self.ws.send(json.dumps({"id": 0, "method": "Browser.close"}))
            except Exception:
                pass
            self.ws.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _capture_token(headless, timeout, state):
    """Open open.spotify.com in a Chromium browser and return the first logged-in token.

    Returns None when the window was closed or (headless) the saved session is
    not logged in; raises TimeoutError when the time runs out.
    """
    browser = _Browser(headless)
    try:
        token_requests = set()  # (session, requestId) awaiting loadingFinished
        body_calls = set()      # our message ids for Network.getResponseBody
        deadline = time.time() + timeout
        for msg in browser.messages(deadline):
            if msg is None:
                continue
            method, params, session = msg.get("method"), msg.get("params", {}), msg.get("sessionId")

            if method == "Target.attachedToTarget" and session is None and params["sessionId"] == browser.page:
                browser.navigate("https://open.spotify.com/")
                if not headless:
                    state.set("waiting", "Waiting for the Spotify window…")

            elif method == "Network.responseReceived" and TOKEN_URL_MARK in params.get("response", {}).get("url", ""):
                token_requests.add((session, params["requestId"]))

            elif method == "Network.loadingFinished" and (session, params.get("requestId")) in token_requests:
                token_requests.discard((session, params["requestId"]))
                body_calls.add(browser.send("Network.getResponseBody", {"requestId": params["requestId"]}, session=session))

            elif msg.get("id") in body_calls:
                body_calls.discard(msg["id"])
                result = msg.get("result")
                if not result:
                    continue
                body = result["body"]
                if result.get("base64Encoded"):
                    body = base64.b64decode(body).decode("utf-8", errors="replace")
                kind, data = _parse_token_body(body)
                if kind == "token":
                    return data
                if headless:
                    return None  # saved session is logged out, needs the visible window
                if kind == "anonymous":
                    state.set("anonymous", "You are not logged in to Spotify. Log in in the window that opened.")
                else:
                    state.set("waiting", f"Spotify returned an error: {data}. Still waiting…")
        if browser.proc.poll() is not None or time.time() < deadline:
            return None  # the user closed the window
        raise TimeoutError
    finally:
        browser.close()


# ── Persisted queries, kept up to date from the web player ────────────────────
def _query(operation):
    """(hash, variables template) for a pathfinder operation: discovered ones first, then the defaults."""
    with _store_lock:
        found = _read_json(_queries_file, {}).get(operation)
    if found:
        return found["hash"], found["variables"]
    return DEFAULT_QUERIES[operation]


def _parse_pathfinder_request(request):
    """(operation, {"hash", "variables"}) from a web-player pathfinder request, or None."""
    if PATHFINDER_URL not in request.get("url", "") or not request.get("postData"):
        return None
    try:
        body = json.loads(request["postData"])
        operation = body["operationName"]
        sha = body["extensions"]["persistedQuery"]["sha256Hash"]
    except (ValueError, KeyError, TypeError):
        return None
    if operation not in DEFAULT_QUERIES or not re.fullmatch(r"[0-9a-f]{64}", sha):
        return None
    return operation, {"hash": sha, "variables": body.get("variables") or {}}


def _discover_queries(timeout=60):
    """Browse a few web-player pages in a headless browser and save the queries it sends.

    Also saves the playlist uri the web player uses for Liked Songs (it differs
    from the library's spotify:collection:tracks). Logged out, only the artist
    and search queries show up; the others keep their previous values.
    Returns the operations found.
    """
    # The pages to visit, each moving on once its query was seen (or after 10 s).
    # profileAttributes and libraryV3 are sent on every page when logged in.
    steps = [
        (f"https://open.spotify.com/artist/{DISCOVERY_ARTIST_ID}", "queryArtistOverview"),
        ("https://open.spotify.com/search/coldplay", "searchDesktop"),
        (LIKED_SONGS_PAGE, "fetchPlaylist"),
    ]
    found, liked_uri = {}, None
    browser = _Browser(headless=True)
    try:
        step, step_started = -1, 0.0
        for msg in browser.messages(time.time() + timeout):
            if found.keys() >= DEFAULT_QUERIES.keys() and liked_uri:
                break
            if browser.page and (step < 0 or steps[step][1] in found or time.time() - step_started > 10):
                step += 1
                if step == len(steps):
                    break
                browser.navigate(steps[step][0])
                step_started = time.time()
            if msg and msg.get("method") == "Network.requestWillBeSent":
                parsed = _parse_pathfinder_request(msg["params"].get("request", {}))
                if parsed:
                    found[parsed[0]] = parsed[1]
                    if parsed[0] == "fetchPlaylist" and steps[step][0] == LIKED_SONGS_PAGE:
                        liked_uri = parsed[1]["variables"].get("uri")
    finally:
        browser.close()

    if found:
        with _store_lock:
            saved = _read_json(_queries_file, {})
            saved.update(found)
            if liked_uri:
                saved["likedSongs"] = {"uri": liked_uri}
            _queries_file.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    return set(found)


def _liked_songs_uri():
    with _store_lock:
        return (_read_json(_queries_file, {}).get("likedSongs") or {}).get("uri")


def _rediscover_queries():
    """Refresh the saved queries (one browser at a time). True if any was found."""
    if not _login_lock.acquire(timeout=60):
        return False
    try:
        return bool(_discover_queries())
    except Exception:
        return False
    finally:
        _login_lock.release()


def _store_captured(data):
    save_token({
        "accessToken": data["accessToken"],
        "accessTokenExpirationTimestampMs": data.get("accessTokenExpirationTimestampMs", 0),
        "clientId": data.get("clientId"),
        "isAnonymous": False,
        "confirmed": False,
    })


def start_login():
    """Open the Spotify window in the background; progress goes to _login_state."""
    if _login_state.running:
        return
    _login_state.set("starting", "Opening Spotify…")

    def run():
        if not _login_lock.acquire(timeout=60):
            _login_state.set("error", "Another Spotify login is still running.")
            return
        try:
            data = _capture_token(headless=False, timeout=300, state=_login_state)
            if data:
                _store_captured(data)
                _login_state.set("success", "Logged in.")
                threading.Thread(target=_rediscover_queries, daemon=True).start()
            else:
                _login_state.set("cancelled", "The Spotify window was closed before logging in.")
        except TimeoutError:
            _login_state.set("timeout", "Timed out waiting for the Spotify login.")
        except Exception as e:
            _login_state.set("error", str(e))
        finally:
            _login_lock.release()

    threading.Thread(target=run, daemon=True).start()


def _refresh_silently():
    """Get a new token from the saved browser session without showing a window."""
    if not _login_lock.acquire(blocking=False):
        return None
    try:
        old = load_token() or {}
        data = _capture_token(headless=True, timeout=30, state=LoginState())
        if not data:
            return None
        _store_captured(data)
        update_token(confirmed=old.get("confirmed", False), profile=old.get("profile"))
        return load_token()
    except Exception:
        return None
    finally:
        _login_lock.release()


def get_access_token():
    """A valid access token, refreshing it if needed. Raises NotAuthenticated."""
    token = load_token()
    if not token:
        raise NotAuthenticated("Not logged in to Spotify.")
    if not _is_fresh(token):
        token = _refresh_silently()
        if not token:
            raise NotAuthenticated("Your Spotify session expired. Log in again.")
    return token["accessToken"]


# ── Spotify requests ──────────────────────────────────────────────────────────
class SpotifyError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class OutdatedQuery(SpotifyError):
    def __init__(self):
        super().__init__(502, "Spotify changed its web API and SpoTracker couldn't adapt. Try again later.")


def _request(url, access_token, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, method="POST" if body is not None else "GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Origin", "https://open.spotify.com")
    req.add_header("Referer", "https://open.spotify.com/")
    req.add_header("app-platform", "WebPlayer")
    if body is not None:
        req.add_header("Content-Type", "application/json;charset=UTF-8")
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 401:
            raise NotAuthenticated("Spotify rejected the token. Log in again.")
        if e.code == 429:
            raise SpotifyError(429, "Spotify is rate-limiting requests. Try again in a minute.")
        if e.code == 412:
            raise OutdatedQuery()
        raise SpotifyError(502, f"Spotify returned HTTP {e.code}.")
    except (URLError, OSError) as e:
        raise SpotifyError(502, f"Could not reach Spotify: {e}")


def _pathfinder(access_token, operation, variables=None):
    """Run a persisted query, overriding some of its variables (e.g. the artist uri).

    On an outdated hash, reads the current queries from the web player and retries once.
    """
    for attempt in (1, 2):
        sha, template = _query(operation)
        try:
            data = _request(PATHFINDER_URL, access_token, {
                "variables": {**template, **(variables or {})},
                "operationName": operation,
                "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}},
            })
        except OutdatedQuery:
            if attempt == 2 or not _rediscover_queries() or _query(operation)[0] == sha:
                raise
            continue
        if data.get("errors") and not data.get("data"):
            raise SpotifyError(502, data["errors"][0].get("message", "Spotify query failed."))
        return data.get("data") or {}


def fetch_profile():
    """The logged-in user's profile (get-spotify-profile.md), cached with the token."""
    token = get_access_token()
    data = _pathfinder(token, "profileAttributes")
    p = (data.get("me") or {}).get("profile")
    if not p:
        raise SpotifyError(502, "Spotify returned no profile.")
    avatars = sorted((p.get("avatar") or {}).get("sources") or [], key=lambda s: s.get("width") or 0)
    profile = {
        "name": p.get("name") or p.get("username"),
        "username": p.get("username"),
        "uri": p.get("uri"),
        "avatar": avatars[-1]["url"] if avatars else None,
    }
    update_token(profile=profile)
    return profile


def _norm(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(name.casefold().split())


def resolve_artist_uri(access_token, name):
    """(uri, approximate) for an artist name from the report; exact matches are cached on disk."""
    with _store_lock:
        cache = _read_json(_artist_uri_file, {})
    if _norm(name) in cache:
        return cache[_norm(name)], False

    # api.spotify.com/v1/search answers 429 to web-player tokens, so search the
    # way the web player does. Results come ordered by relevance.
    data = _pathfinder(access_token, "searchDesktop", {"searchTerm": name})
    items = [i.get("data") or {} for i in ((data.get("searchV2") or {}).get("artists") or {}).get("items") or []]
    items = [a for a in items if a.get("uri", "").startswith("spotify:artist:")]
    exact = [a for a in items if _norm((a.get("profile") or {}).get("name", "")) == _norm(name)]
    if not exact:
        # No artist with exactly this name: offer the best match, but don't cache it.
        return (items[0]["uri"], True) if items else (None, False)

    with _store_lock:
        cache = _read_json(_artist_uri_file, {})
        cache[_norm(name)] = exact[0]["uri"]
        _artist_uri_file.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    return exact[0]["uri"], False


def _biggest(sources):
    sources = [s for s in sources or [] if s.get("url")]
    return max(sources, key=lambda s: s.get("width") or s.get("maxWidth") or 0)["url"] if sources else None


def _smallest_over(sources, minimum=64):
    sources = sorted((s for s in sources or [] if s.get("url")), key=lambda s: s.get("width") or 0)
    for s in sources:
        if (s.get("width") or 0) >= minimum:
            return s["url"]
    return sources[-1]["url"] if sources else None


def _plain_text(html_text):
    """Spotify bios are HTML (links to other artists, &#64; entities): keep just the text."""
    if not html_text:
        return None
    return html.unescape(re.sub(r"<[^>]+>", "", html_text)).strip() or None


def summarize_artist(a):
    """The parts of artistUnion (get-artist-profile.md) the report shows."""
    stats = a.get("stats") or {}
    disco = a.get("discography") or {}
    latest = disco.get("latest")
    top_tracks = []
    for item in ((disco.get("topTracks") or {}).get("items") or [])[:5]:
        t = item.get("track") or {}
        top_tracks.append({
            "name": t.get("name"),
            "playcount": int(t["playcount"]) if str(t.get("playcount", "")).isdigit() else None,
            "cover": _smallest_over(((t.get("albumOfTrack") or {}).get("coverArt") or {}).get("sources")),
            "durationMs": (t.get("duration") or {}).get("totalMilliseconds"),
        })
    return {
        "name": (a.get("profile") or {}).get("name"),
        "uri": a.get("uri"),
        "url": (a.get("sharingInfo") or {}).get("shareUrl"),
        "verified": bool(((a.get("onPlatformReputationTrait") or {}).get("verification") or {}).get("isVerified")),
        "avatar": _biggest(((a.get("visuals") or {}).get("avatarImage") or {}).get("sources")),
        "header": _biggest(((a.get("headerImage") or {}).get("data") or {}).get("sources")),
        "bio": _plain_text(((a.get("profile") or {}).get("biography") or {}).get("text")),
        "followers": stats.get("followers"),
        "monthlyListeners": stats.get("monthlyListeners"),
        "worldRank": stats.get("worldRank") or None,
        "topCities": [
            {"city": c.get("city"), "country": c.get("country"), "listeners": c.get("numberOfListeners")}
            for c in ((stats.get("topCities") or {}).get("items") or [])[:5]
        ],
        "topTracks": top_tracks,
        "albums": (disco.get("albums") or {}).get("totalCount", 0),
        "singles": (disco.get("singles") or {}).get("totalCount", 0),
        "latest": latest and {
            "name": latest.get("name"),
            "type": latest.get("type"),
            "year": (latest.get("date") or {}).get("year"),
            "cover": _smallest_over((latest.get("coverArt") or {}).get("sources")),
        },
        "relatedArtists": [
            r.get("profile", {}).get("name")
            for r in (((a.get("relatedContent") or {}).get("relatedArtists") or {}).get("items") or [])[:8]
        ],
    }


_artist_cache = {}


def fetch_artist(name):
    key = _norm(name)
    if key in _artist_cache:
        return _artist_cache[key]
    token = get_access_token()
    uri, approximate = resolve_artist_uri(token, name)
    if not uri:
        raise SpotifyError(404, f"Couldn't find “{name}” on Spotify.")
    data = _pathfinder(token, "queryArtistOverview", {"uri": uri})
    artist = data.get("artistUnion")
    if not artist or artist.get("__typename") != "Artist":
        raise SpotifyError(404, f"Spotify has no artist page for “{name}”.")
    _artist_cache[key] = dict(summarize_artist(artist), approximate=approximate)
    return _artist_cache[key]


# ── Playlists ────────
_playlists_lock = threading.Lock()  # one fetch at a time; a second request waits and reuses the cache

def track_keys(name, artists):
    """Keys that match this track to the listening history.

    The CSV stores the main artist and the title as Spotify shows them; the
    reports merge "(feat. …)" variants with feats.py, so the same normalisation
    is used here. One key per artist, in case the CSV has another one as main.
    """
    import feats
    return [feats.song_key(a, name or "") for a in artists if a]


def _summarize_track(item):
    data = (item.get("itemV2") or {}).get("data") or {}
    if data.get("__typename") != "Track":
        return None  # episodes, unavailable or local files
    artists = [(a.get("profile") or {}).get("name") for a in (data.get("artists") or {}).get("items") or []]
    album = data.get("albumOfTrack") or {}
    return {
        "uri": data.get("uri"),
        "name": data.get("name"),
        "artists": [a for a in artists if a],
        "album": album.get("name"),
        "cover": _smallest_over((album.get("coverArt") or {}).get("sources")),
        "durationMs": (data.get("trackDuration") or {}).get("totalMilliseconds"),
        "addedAt": (item.get("addedAt") or {}).get("isoString"),
        "playcount": int(data["playcount"]) if str(data.get("playcount", "")).isdigit() else None,
        "keys": track_keys(data.get("name"), artists),
    }


def _fetch_playlist_tracks(token, uri):
    """(playlistV2 without its items, [tracks]) reading every page."""
    tracks, offset, meta = [], 0, None
    while True:
        data = _pathfinder(token, "fetchPlaylist", {"uri": uri, "offset": offset, "limit": PLAYLIST_PAGE})
        playlist = data.get("playlistV2") or {}
        if playlist.get("__typename") != "Playlist":
            return None, []
        content = playlist.get("content") or {}
        meta = meta or playlist
        items = content.get("items") or []
        tracks.extend(t for t in map(_summarize_track, items) if t)
        offset += PLAYLIST_PAGE
        if not items or offset >= (content.get("totalCount") or 0):
            return meta, tracks


def _library_playlists(token):
    """Playlist entries of the user's library (folders flattened), Liked Songs included."""
    entries, offset = [], 0
    while True:
        data = _pathfinder(token, "libraryV3", {"offset": offset, "limit": 50})
        library = ((data.get("me") or {}).get("libraryV3")) or {}
        items = library.get("items") or []
        for it in items:
            d = (it.get("item") or {}).get("data") or {}
            if d.get("__typename") in ("Playlist", "PseudoPlaylist"):
                entries.append(d)
        offset += 50
        if not items or offset >= (library.get("totalCount") or 0):
            return entries


def _playlist_summary(entry, meta, tracks, liked_uri, me):
    liked = entry.get("__typename") == "PseudoPlaylist"
    owner = ((entry.get("ownerV2") or {}).get("data")) or {}
    images = (entry.get("images") or {}).get("items") or []
    uri = liked_uri if liked else entry.get("uri")
    return {
        "uri": uri,
        "name": entry.get("name") or (meta or {}).get("name"),
        "description": _plain_text(entry.get("description")),
        "image": _smallest_over((entry.get("image") or {}).get("sources") if liked
                                else (images[0].get("sources") if images else None), 200),
        "owner": owner.get("name") if not liked else (me or {}).get("name"),
        "own": liked or bool(me and owner.get("username") == me.get("username")),
        "liked": liked,
        "followers": (meta or {}).get("followers"),
        "url": LIKED_SONGS_PAGE if liked else f"https://open.spotify.com/playlist/{uri.rsplit(':', 1)[-1]}",
        "totalTracks": len(tracks),
        "tracks": tracks,
    }


def fetch_playlists(refresh=False):
    """The user's playlists with all their tracks.

    Each playlist is cached on disk by its revision, so only changed ones are
    fetched again (Liked Songs by its count; refresh=True refetches everything).
    """
    from concurrent.futures import ThreadPoolExecutor

    with _playlists_lock:
        token = get_access_token()
        me = (load_token() or {}).get("profile")
        liked_uri = _liked_songs_uri()
        entries = _library_playlists(token)
        if not liked_uri and any(e.get("__typename") == "PseudoPlaylist" for e in entries):
            _rediscover_queries()  # learns the Liked Songs playlist uri from the web player
            liked_uri = _liked_songs_uri()
        entries = [e for e in entries if e.get("__typename") == "Playlist" or liked_uri]

        with _store_lock:
            cache = {} if refresh else _read_json(_playlists_file, {})

        def revision(e):
            return f"count:{e.get('count')}" if e.get("__typename") == "PseudoPlaylist" else e.get("revisionId")

        def load(e):
            uri = liked_uri if e.get("__typename") == "PseudoPlaylist" else e.get("uri")
            cached = cache.get(uri)
            if cached and cached.get("revision") == revision(e):
                return uri, cached
            meta, tracks = _fetch_playlist_tracks(token, uri)
            if meta is None:
                return uri, None  # deleted or not visible any more
            if e.get("__typename") == "PseudoPlaylist" and meta.get("format") != "liked-songs":
                return uri, None  # the discovered uri isn't Liked Songs after all
            return uri, {"revision": revision(e), "playlist": _playlist_summary(e, meta, tracks, liked_uri, me)}

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(load, entries))

        fresh = {uri: entry for uri, entry in results if entry}
        with _store_lock:
            _playlists_file.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
        return {
            "fetchedAt": int(time.time() * 1000),
            "playlists": [fresh[uri]["playlist"] for uri, entry in results if entry],
        }


# ── HTTP server ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        return origin in (None, "null")  # reports are opened from file://

    def _send(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204 if self._origin_allowed() else 403)
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, verb):
        if not self._origin_allowed():
            return self._send(403, {"error": "Forbidden"})
        url = urlparse(self.path)
        route = (verb, url.path.rstrip("/"))
        query = parse_qs(url.query)
        try:
            if route == ("GET", "/api/status"):
                token = load_token()
                return self._send(200, {
                    "authenticated": bool(token),
                    "confirmed": bool(token and token.get("confirmed")),
                    "profile": token.get("profile") if token else None,
                    "login": _login_state.snapshot(),
                })
            if route == ("POST", "/api/auth/login"):
                start_login()
                return self._send(202, _login_state.snapshot())
            if route == ("GET", "/api/auth/state"):
                return self._send(200, _login_state.snapshot())
            if route == ("POST", "/api/auth/confirm"):
                update_token(confirmed=True)
                return self._send(200, {"confirmed": True})
            if route == ("POST", "/api/auth/logout"):
                clear_login()
                _login_state.set("idle")
                return self._send(200, {"authenticated": False})
            if route == ("GET", "/api/profile"):
                return self._send(200, fetch_profile())
            if route == ("GET", "/api/artist"):
                name = (query.get("name") or [""])[0].strip()
                if not name:
                    return self._send(400, {"error": "Missing artist name."})
                return self._send(200, fetch_artist(name))
            if route == ("GET", "/api/playlists"):
                return self._send(200, fetch_playlists(refresh=(query.get("refresh") or [""])[0] == "1"))
            return self._send(404, {"error": "Not found"})
        except NotAuthenticated as e:
            return self._send(401, {"error": str(e)})
        except SpotifyError as e:
            return self._send(e.status, {"error": str(e)})
        except Exception as e:
            return self._send(500, {"error": f"Unexpected error: {e}"})

    def log_message(self, format, *args):
        pass


_server = None


def start_server():
    """Serve the API in a background thread. Returns False if the port is taken."""
    global _server
    if _server is not None:
        return True
    try:
        _server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return False
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return True


if __name__ == "__main__":
    # Development: run the API on its own, without the tray app.
    if not start_server():
        raise SystemExit(f"Port {PORT} is already in use (is SpoTracker running?).")
    print(f"Spotify API on http://127.0.0.1:{PORT} — Ctrl+C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
