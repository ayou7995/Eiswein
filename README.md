# Eiswein

> 繁體中文版本見 [`README_zhTW.md`](./README_zhTW.md).

Eiswein is a personal stock-market decision-support tool. It tracks a
watchlist of US-listed tickers, computes 12 technical and market-
regime indicators every day, and surfaces the result as a simple
"buy / hold / watch / reduce / exit" signal per ticker plus an
overall market posture (進攻 / 正常 / 防守).

You run it on your own laptop. No data leaves your machine. There is
no auto-trading — every decision is still yours.

**Inspired by** Heaton's Sherry trading system
([背景 / philosophy](./docs/SHERRY_SYSTEM.md)). **Not affiliated with**
Heaton or his Patreon.

---

## What you need before installing

| Required | Why |
|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs the app in a single container |
| `git` | To `git clone` and later `make update` |
| Python ≥ 3.10 with `venv` | One-shot use during install — `make install` builds its own `.venv-bootstrap/` so nothing pollutes your system Python |

| Optional (asked during install) | Why |
|---|---|
| Free [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html) | Powers macro indicators (CPI, FOMC, yield curve, VIX) |
| Gmail with [App Password](https://myaccount.google.com/apppasswords) | Delivers the daily catalyst-digest email |
| Schwab developer account ([dev portal](https://developer.schwab.com/)) | Read your brokerage positions via the in-app `連接 Schwab` card |
| [`mkcert`](https://github.com/FiloSottile/mkcert) | Only if you enable Schwab — generates a trusted local HTTPS cert |

You can skip every "optional" — the app still runs in pure
decision-support mode using free Yahoo Finance data.

---

## 5-minute install

```sh
git clone <this-repo-url> eiswein
cd eiswein

# Interactive wizard. First run creates a private .venv-bootstrap/
# with bcrypt + zxcvbn, then walks you through admin login + FRED /
# SMTP / Schwab (each is skippable). Your system Python is not touched.
make install

# Boot in the background
make start

# Open in your browser
open http://localhost:8080
```

First boot needs ~30 seconds to build the Docker image. Subsequent
`make start` is instant.

Log in with the username/password you set during `make install`. Add
some tickers via the sidebar `+` button. Wait until 06:30 ET tomorrow
(or until you next start the app — see "Automatic scheduling" below)
for the first signals to compute.

---

## Daily operations

| Command | What it does |
|---|---|
| `make start` | Boot the stack in the background. Safe to run repeatedly. |
| `make stop` | Stop the container. Your data is preserved. |
| `make logs` | Tail backend logs in your terminal. `Ctrl+C` to detach. |
| `make update` | `git pull` + rebuild image + restart. Use this to take a new release. |
| `make uninstall` | **Destructive.** Removes the container, image, `.env`, `data/`, and `certs/`. Source code stays. |
| `make help` | List every available command. |

The `make dev` target is for editing code on your own machine — it
runs Vite + uvicorn in the foreground with hot reload. Most users
never need it.

---

## Automatic scheduling

Once the container is running, an in-process scheduler fires four
jobs without any external cron setup. Times are in US Eastern
(automatic DST handling):

| Job | Cron | What it does |
|---|---|---|
| `daily_update` | Every day **06:30 ET** | Fetches new prices, recomputes the 12 indicators, refreshes the catalyst calendar, optionally sends a digest email |
| `backup` | Every day 07:00 ET | Snapshots `data/eiswein.db` into `data/backups/` |
| `token_reminder` | Every day 09:15 ET | If Schwab is connected, emails when the refresh token is nearing expiry |
| `vacuum` | First Sunday of each month, 03:00 ET | `VACUUM` the SQLite file to reclaim space |

If your laptop is asleep at the scheduled time, the run is missed
**but** the next time the container starts, `daily_update` runs once
to catch up — its gap-detection logic fills in any missing trading
days. So in practice: as long as you bring the laptop online once
every few days, indicators stay current.

---

## Advanced setup

### Connect Schwab (read-only positions)

1. Register a Schwab developer app at
   <https://developer.schwab.com/>.
2. Pick **Individual Developer**.
3. Set the **Callback URL** to exactly:
   `https://localhost:8080/api/v1/broker/schwab/callback`
4. Wait for approval (Schwab typically responds within 1–3 business
   days).
5. Re-run `make install` and answer "yes" to the Schwab question.
   The wizard will run `mkcert` to generate the local HTTPS cert pair
   into `certs/`.
6. `make start` again — the app now serves over HTTPS. Open
   `https://localhost:8080`, go to 設定 → 連接 Schwab.

See [`docs/SETUP_GUIDE.md`](./docs/SETUP_GUIDE.md) for the full
walkthrough with screenshots.

### Enable email reminders

Run `make install` (re-running is safe) and pick the SMTP branch:

- **Gmail** — needs an [App Password](https://myaccount.google.com/apppasswords)
  (requires 2FA on your account). Real mail lands in the recipient
  inbox.
- **Mailpit** — no real delivery; mail is captured in a local web UI
  at <http://localhost:8025>. Useful for previewing email layout.
  Start the stack with `COMPOSE_PROFILES=email make start`.

### FRED API key

Free, takes ~30 seconds: <https://fred.stlouisfed.org/docs/api/api_key.html>.
Without it, macro indicators (CPI, yield curve, Fed funds rate, VIX)
fall back to "data unavailable" badges.

---

## Troubleshooting

**Browser shows "Not Secure" warning.** Expected on the local
self-signed cert. Click "Advanced" → "Proceed". The connection is
HTTPS but Chrome doesn't trust the mkcert root unless you ran
`mkcert -install` (the bootstrap script does this automatically when
generating Schwab certs).

**`make start` fails with port 8080 in use.** Another process is
listening on 8080. Either stop it, or edit `docker-compose.yml` to
map a different host port.

**`make start` fails with "Cannot connect to Docker daemon".**
Docker Desktop isn't running. Start it from your Applications
folder.

**Login form rejects my password.** During `make install` you
entered a username/password — the password is bcrypt-hashed into
`.env`. If you don't remember, run `make uninstall && make install`
(this wipes your database too) or edit `ADMIN_PASSWORD_HASH` in
`.env` directly using `scripts/set_password.py`.

**`make install` accepted my new password but the login still
rejects it.** Almost always means a stale `data/eiswein.db` from a
previous install survived. The admin row inside that DB outlives
`.env` — at first boot the container reads the admin's stored hash
from the DB, not `.env`. Recent `make install` runs offer to wipe
`data/` for you; older installs may have left it behind. Recovery:
```sh
make stop
rm -rf data/                  # also clears any login lockout
make start
```
Or, if the DB has data you want to keep, run
`scripts/reset_password_offline.py` to update the stored hash
without nuking the DB.

**`make update` says "Your branch is behind" but nothing changes.**
You might have local edits. Inspect with `git status` first.

**Schwab "Connect" button gives a 401.** See
[`docs/SETUP_GUIDE.md`](./docs/SETUP_GUIDE.md) — almost always a host
mismatch (`localhost` vs `127.0.0.1`); the Vite dev redirect handles
it for `make dev` but the production container uses `localhost:8080`
exclusively.

---

## Privacy

- **Everything stays on your laptop.** The app talks to Yahoo
  Finance (for prices) and optionally FRED (for macro data), Gmail
  (for outbound mail), and Schwab (for your positions). No analytics,
  no telemetry, no cloud sync.
- The SQLite database, indicator cache, and any TLS keys live under
  `./data/` and `./certs/`. Both are excluded from git.
- `.env` holds your secrets in plaintext (`chmod 600`). Treat it
  like any other secret file.

---

## For developers

If you want to read or modify the code, the architecture and design
decisions are in:

- [`CLAUDE.md`](./CLAUDE.md) — project structure, invariants, conventions
- [`docs/IMPLEMENTATION_PLAN.md`](./docs/IMPLEMENTATION_PLAN.md) — milestone roadmap
- [`docs/STAFF_REVIEW_DECISIONS.md`](./docs/STAFF_REVIEW_DECISIONS.md) — locked technical decisions
- [`docs/DESIGN_DECISIONS.md`](./docs/DESIGN_DECISIONS.md) — original scoping
- [`AGENTS.md`](./AGENTS.md) — maintenance contract for distribution changes

For day-to-day development use `make dev` (foreground Vite + uvicorn
with hot reload). Tests live in `backend/tests/` (pytest) and
`frontend/src/**/*.test.tsx` (vitest). `make test` runs the backend
suite; `cd frontend && npm test` runs the frontend.

---

## License

See [`NOTICE.md`](./NOTICE.md). Private repository, source-available
only to invited collaborators.
