// Spotify login, account menu (top right) and artist modal, shared by the report pages.
//
// A page includes spotify.css, has <div class="account" id="account"></div> in its
// header and <p class="spotify-status" id="auth-status"></p> where messages go,
// sets window.SPOTRACKER_API_PORT and loads this file at the end of <body>.
// It reacts to the login with Spotify.onChange(state => …).

const Spotify = (() => {
	const API_BASE = `http://127.0.0.1:${window.SPOTRACKER_API_PORT}`;
	const LOGO = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>';

	// ready: the first status check finished; online: the tray app answered
	const state = { ready: false, online: false, authenticated: false, confirmed: false, profile: null };
	const listeners = [];
	const $ = id => document.getElementById(id);

	function esc(s) {
		return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
	}
	function formatNumber(n) { return Number(n || 0).toLocaleString(); }
	function formatDuration(sec) {
		const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
		return h > 0 ? `${h}h ${m}m` : `${m}m`;
	}

	function onChange(fn) {
		listeners.push(fn);
		if (state.ready) fn(state);
	}
	function notify() { listeners.forEach(fn => fn(state)); }

	// ── Local API (served by the SpoTracker tray app) ────────────────────────
	async function api(path, method = "GET") {
		let resp;
		try {
			resp = await fetch(`${API_BASE}${path}`, { method });
		} catch (e) {
			const err = new Error("SpoTracker isn't running. Start it from the Start Menu to use Spotify features.");
			err.offline = true;
			throw err;
		}
		const data = await resp.json().catch(() => ({}));
		if (!resp.ok) {
			const err = new Error(data.error || `Request failed (${resp.status})`);
			err.status = resp.status;
			if (resp.status === 401 && state.authenticated) loggedOut(err.message);
			throw err;
		}
		return data;
	}

	function setStatus(msg, type) {
		const el = $("auth-status");
		if (!el) return;
		el.textContent = msg || "";
		el.className = "spotify-status" + (type ? " " + type : "");
	}

	// ── Account (top right) ──────────────────────────────────────────────────
	function renderAccount() {
		$("account").innerHTML =
			`<button class="spotify-login-btn" id="btn-spotify-login">${LOGO} Log in</button>` +
			`<button class="account-btn" id="account-btn" hidden aria-haspopup="menu" aria-expanded="false" aria-controls="account-menu"></button>` +
			`<div class="account-menu" id="account-menu" role="menu" hidden></div>`;
		$("btn-spotify-login").addEventListener("click", login);
		$("account-btn").addEventListener("click", toggleMenu);
		$("account-menu").addEventListener("click", e => {
			const action = e.target.closest("[data-action]")?.dataset.action;
			if (action === "yes") confirmUser(true);
			if (action === "no") confirmUser(false);
			if (action === "logout") logout();
		});
	}

	function showLoginButton(show) {
		$("btn-spotify-login").hidden = !show;
		$("btn-spotify-login").disabled = false;
		$("account-btn").hidden = show;
		if (show) closeMenu();
	}

	function avatarHtml(profile) {
		return profile.avatar
			? `<img class="account-avatar" src="${esc(profile.avatar)}" alt="" />`
			: `<span class="account-avatar">${esc((profile.name || "?").charAt(0).toUpperCase())}</span>`;
	}

	function showProfile(profile) {
		state.profile = profile;
		const btn = $("account-btn");
		btn.innerHTML = avatarHtml(profile);
		btn.title = profile.name;
		btn.setAttribute("aria-label", `Spotify account: ${profile.name}`);
		showLoginButton(false);
		renderMenu();
		if (!state.confirmed) openMenu(); // ask right away whether this is the right account
	}

	function renderMenu() {
		const p = state.profile;
		$("account-btn").classList.toggle("unconfirmed", !state.confirmed);
		$("account-menu").innerHTML =
			`<div class="account-head">` +
				avatarHtml(p) +
				`<div style="min-width:0"><div class="account-name">${esc(p.name)}</div>` +
				`<div class="account-id" title="${esc(p.username)}">ID: ${esc(p.username)}</div></div>` +
			`</div>` +
			(state.confirmed
				? `<div class="account-divider"></div>` +
				  `<button class="account-item" role="menuitem" data-action="logout">Log out</button>`
				: `<p class="account-question">Is this your Spotify account?</p>` +
				  `<div class="account-actions">` +
					`<button class="confirm-yes" data-action="yes">Yes, it's me</button>` +
					`<button class="confirm-no" data-action="no">Not me</button>` +
				  `</div>`);
	}

	function openMenu() {
		if (!state.profile) return; // nothing to show while logged out
		$("account-menu").hidden = false;
		$("account-btn").setAttribute("aria-expanded", "true");
	}
	function closeMenu() {
		$("account-menu").hidden = true;
		$("account-btn").setAttribute("aria-expanded", "false");
	}
	function toggleMenu() {
		if ($("account-menu").hidden) openMenu(); else closeMenu();
	}

	// ── Login flow ───────────────────────────────────────────────────────────
	async function checkStatus() {
		let status;
		try {
			status = await api("/api/status");
		} catch (e) {
			state.ready = true;
			notify();
			return; // tray app not running: the login button explains it when clicked
		}
		state.online = true;
		if (["starting", "waiting", "anonymous"].includes(status.login.status)) {
			$("btn-spotify-login").disabled = true;
			pollLogin();
		} else if (status.authenticated) {
			state.authenticated = true;
			state.confirmed = status.confirmed;
			if (status.profile) showProfile(status.profile);
			else await loadProfile();
		}
		state.ready = true;
		notify();
	}

	async function login() {
		const ok = confirm(
			"SpoTracker will open open.spotify.com in a browser window.\n\n" +
			"Log in to Spotify there; the window closes by itself once you're logged in."
		);
		if (!ok) return;
		$("btn-spotify-login").disabled = true;
		try {
			await api("/api/auth/login", "POST");
		} catch (e) {
			setStatus(e.message, "error");
			$("btn-spotify-login").disabled = false;
			return;
		}
		pollLogin();
	}

	async function pollLogin() {
		let s;
		try {
			s = await api("/api/auth/state");
		} catch (e) {
			setStatus(e.message, "error");
			showLoginButton(true);
			return;
		}
		switch (s.status) {
			case "success":
				state.authenticated = true;
				state.confirmed = false;
				setStatus("Logged in. Loading your profile…", "success");
				await loadProfile();
				notify();
				return;
			case "anonymous":
				setStatus(s.message, "warning");
				break;
			case "error":
			case "cancelled":
			case "timeout":
				setStatus(s.message, "error");
				showLoginButton(true);
				return;
			default:
				setStatus(s.message || "Opening Spotify…", "");
		}
		setTimeout(pollLogin, 1000);
	}

	async function loadProfile() {
		try {
			showProfile(await api("/api/profile"));
			setStatus("", "");
		} catch (e) {
			if (e.status === 401) loggedOut();
			setStatus("Couldn't load your Spotify profile: " + e.message, "error");
		}
	}

	async function confirmUser(isMe) {
		if (!isMe) {
			await logout();
			setStatus("Logged out. Log in again with your own Spotify account.", "warning");
			return;
		}
		try {
			await api("/api/auth/confirm", "POST");
		} catch (e) {
			setStatus(e.message, "error");
			return;
		}
		state.confirmed = true;
		renderMenu();
		closeMenu();
		setStatus("Connected to Spotify ✓", "success");
		notify();
	}

	function loggedOut(message) {
		state.authenticated = state.confirmed = false;
		state.profile = null;
		showLoginButton(true);
		if (message) setStatus(message, "warning");
		notify();
	}

	async function logout() {
		try { await api("/api/auth/logout", "POST"); } catch (e) { /* ignore */ }
		loggedOut();
		setStatus("Logged out.", "");
	}

	// Pages call this when a feature needs a confirmed login
	function requireLogin(what) {
		if (state.authenticated && state.confirmed) return true;
		setStatus(state.authenticated ? `Confirm your Spotify account first to see ${what}.`
		                              : `Log in with Spotify to see ${what}.`, "warning");
		window.scrollTo({ top: 0, behavior: "smooth" });
		if (state.authenticated) openMenu();
		return false;
	}

	// ── Artist modal ─────────────────────────────────────────────────────────
	// Pages can set Spotify.myStatsFor = name => ({ plays, seconds, tracks }) to show "You: …"
	function renderModalShell() {
		const el = document.createElement("div");
		el.className = "artist-modal-overlay";
		el.id = "artist-modal-overlay";
		el.innerHTML =
			`<div class="artist-modal" role="dialog" aria-modal="true" aria-labelledby="artist-modal-header-info">` +
				`<div class="artist-modal-header" id="artist-modal-header">` +
					`<button class="artist-modal-close" aria-label="Close">✕</button>` +
					`<div class="artist-modal-header-info" id="artist-modal-header-info"></div>` +
				`</div>` +
				`<div class="artist-modal-body" id="artist-modal-body">` +
					`<div class="artist-modal-loading" id="artist-modal-loading"><div class="spinner"></div><p>Loading artist info…</p></div>` +
					`<div id="artist-modal-content" style="display:none"></div>` +
				`</div>` +
			`</div>`;
		el.addEventListener("click", e => {
			if (e.target === el || e.target.closest(".artist-modal-close")) closeArtist();
		});
		document.body.appendChild(el);
	}

	function modalContent(html) {
		$("artist-modal-loading").style.display = "none";
		$("artist-modal-content").innerHTML = html;
		$("artist-modal-content").style.display = "";
	}

	async function openArtist(name) {
		if (!requireLogin("artist details")) return;
		$("artist-modal-loading").style.display = "";
		$("artist-modal-content").style.display = "none";
		$("artist-modal-header-info").innerHTML = `<div><div class="artist-modal-name">${esc(name)}</div></div>`;
		$("artist-modal-header").style.backgroundImage = "";
		$("artist-modal-overlay").classList.add("visible");
		document.body.style.overflow = "hidden";
		try {
			renderArtist(await api(`/api/artist?name=${encodeURIComponent(name)}`), name);
		} catch (e) {
			modalContent(`<p class="artist-modal-error">${esc(e.message)}</p>`);
		}
	}

	function renderArtist(artist, reportName) {
		if (artist.header || artist.avatar) {
			$("artist-modal-header").style.backgroundImage = `url("${encodeURI(artist.header || artist.avatar)}")`;
		}
		$("artist-modal-header-info").innerHTML =
			(artist.avatar ? `<img class="artist-modal-avatar" src="${esc(artist.avatar)}" alt="" />` : "") +
			`<div><div class="artist-modal-name">${esc(artist.name)}</div>` +
			(artist.verified ? `<span class="artist-modal-verified">✓ Verified Artist</span>` : "") + `</div>`;

		let html = "";
		if (artist.approximate) {
			html += `<p class="artist-modal-note">No artist named “${esc(reportName)}” on Spotify; showing the closest match.</p>`;
		}
		const mine = Spotify.myStatsFor && Spotify.myStatsFor(reportName);
		if (mine) {
			html += `<p class="artist-modal-mine">You: <strong>${formatNumber(mine.plays)} plays</strong> · ${formatDuration(mine.seconds)}` +
				(mine.tracks ? ` · ${mine.tracks} tracks` : "") + `</p>`;
		}
		html +=
			`<div class="artist-modal-stats">` +
				`<div class="artist-modal-stat"><div class="artist-modal-stat-value">${formatNumber(artist.monthlyListeners)}</div><div class="artist-modal-stat-label">Monthly listeners</div></div>` +
				`<div class="artist-modal-stat"><div class="artist-modal-stat-value">${formatNumber(artist.followers)}</div><div class="artist-modal-stat-label">Followers</div></div>` +
				`<div class="artist-modal-stat"><div class="artist-modal-stat-value">${artist.worldRank ? "#" + formatNumber(artist.worldRank) : "—"}</div><div class="artist-modal-stat-label">World rank</div></div>` +
			`</div>`;
		if (artist.topTracks.length) {
			html += `<div class="artist-modal-section"><h4 class="artist-modal-section-title">Popular tracks</h4>`;
			artist.topTracks.forEach(t => {
				html +=
					`<div class="artist-modal-top-track">` +
						(t.cover ? `<img class="artist-modal-top-track-cover" src="${esc(t.cover)}" alt="" />` : `<div class="artist-modal-top-track-cover"></div>`) +
						`<div class="artist-modal-top-track-info"><div class="artist-modal-top-track-name" translate="no">${esc(t.name)}</div>` +
						`<div class="artist-modal-top-track-plays">${t.playcount != null ? formatNumber(t.playcount) + " plays" : ""}</div></div>` +
					`</div>`;
			});
			html += `</div>`;
		}
		if (artist.topCities.length) {
			html += `<div class="artist-modal-section"><h4 class="artist-modal-section-title">Where people listen</h4><ul class="artist-modal-cities">`;
			artist.topCities.forEach(c => {
				html += `<li class="artist-modal-city"><span class="artist-modal-city-name">${esc(c.city)}, ${esc(c.country)}</span><span class="artist-modal-city-count">${formatNumber(c.listeners)} listeners</span></li>`;
			});
			html += `</ul></div>`;
		}
		if (artist.bio) {
			html += `<div class="artist-modal-section"><h4 class="artist-modal-section-title">About</h4><p class="artist-modal-bio">${esc(artist.bio)}</p></div>`;
		}
		if (artist.url) {
			html += `<a class="artist-modal-open" href="${esc(artist.url)}" target="_blank" rel="noopener">Open in Spotify ↗</a>`;
		}
		modalContent(html);
		$("artist-modal-body").scrollTop = 0;
	}

	function closeArtist() {
		$("artist-modal-overlay").classList.remove("visible");
		document.body.style.overflow = "";
	}

	function artistLink(name) {
		return `<a class="artist-link" href="#" data-artist="${esc(name)}" translate="no">${esc(name)}</a>`;
	}

	// ── Wiring ───────────────────────────────────────────────────────────────
	renderAccount();
	renderModalShell();
	document.addEventListener("keydown", e => {
		if (e.key === "Escape") { closeArtist(); closeMenu(); }
	});
	document.addEventListener("click", e => {
		if (!e.target.closest("#account")) closeMenu();
		const el = e.target.closest("[data-artist]");
		if (el) {
			e.preventDefault();
			openArtist(el.dataset.artist);
		}
	});
	checkStatus();

	return { state, api, esc, formatNumber, formatDuration, onChange, login, requireLogin, setStatus, artistLink, openArtist, myStatsFor: null };
})();
