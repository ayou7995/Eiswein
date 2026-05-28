# Setup Guide

> 繁體中文版見 [`SETUP_GUIDE_zhTW.md`](./SETUP_GUIDE_zhTW.md).

Deep-dive for each optional integration. The interactive
`make install` wizard already asks for these values — this document
explains *what* you're giving it and how to get the credentials.

If you've never run the wizard, start with the
[`README`](../README.md) quickstart. This guide assumes you've
already cloned the repo and run `make install` at least once.

---

## 1. FRED API key (macro indicators)

### What it unlocks

The Federal Reserve Economic Data API powers four of the twelve
indicators Eiswein computes:

- **VIX** — volatility index level + trend
- **10Y–2Y yield spread** — recession early warning
- **Fed Funds Rate** — current rate + market expectations
- **DXY** — dollar index trend
- **CPI / PCE / PPI release dates** — for the catalyst calendar

Without a key, these tiles fall back to "資料無法取得" / "Data
unavailable" badges. The per-ticker signals (price-vs-MA, RSI,
MACD, etc.) still work normally because they use Yahoo Finance.

### How to get a key

1. Go to
   <https://fred.stlouisfed.org/docs/api/api_key.html>.
2. Click **My Account** (sign up if you don't have a St. Louis Fed
   account — free, only needs an email).
3. Click **Request API Key**. Type a one-line description (e.g.
   "personal market dashboard"). The key is issued instantly.
4. Copy the key string.
5. Either re-run `make install` (it'll ask again) or edit `.env`
   directly: set `FRED_API_KEY=…`. Then `make stop && make start`.

### How to verify

After `make start`, hit:

```
curl http://localhost:8080/api/v1/health
```

The response includes `data_sources` — `fred` should show
`status: "ok"` once an indicator query has run successfully.

---

## 2. SMTP for email reminders

You have three options. The wizard walks you through whichever you
pick.

### Option A — Gmail App Password (delivers real email)

**Requirements**: a Gmail account with 2-Step Verification enabled.

1. Go to <https://myaccount.google.com/security>. Confirm **2-Step
   Verification** is on. Turn it on if not.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Pick **Other (Custom name)** → name it "Eiswein" → **Generate**.
4. Copy the 16-character password (no spaces).
5. Run `make install` and pick the Gmail branch:
   - Gmail address: your full email
   - App Password: paste the 16 chars
   - From address: defaults to your email
   - Send to: where to receive the digests (often your own email)

The catalyst digest fires once at the end of every successful
`daily_update`. You can disable email later by running `make install`
again and picking "skip".

### Option B — Mailpit (local preview only)

Mailpit is a tiny SMTP server that catches outbound mail in a web UI.
**It never delivers anywhere.** Use this if you want to see what the
catalyst digest looks like without spamming yourself, or for
development.

1. `make install` → SMTP question → choose **m** (Mailpit).
2. Start the stack with the email profile:
   ```sh
   COMPOSE_PROFILES=email make start
   ```
3. Open <http://localhost:8025> — the Mailpit inbox.

### Option C — skip

Pick **s** (skip) at the SMTP question, or leave `SMTP_HOST=` empty
in `.env`. The catalyst digest job logs `email_skipped:
not_configured` and continues. No errors, no dropped data — just no
email.

---

## 3. Schwab broker integration

This unlocks the in-app **設定 → 連接 Schwab** card, which lets the
app read your brokerage positions over Schwab's official OAuth flow.
**Read-only**. There is no order-placement code path in Eiswein.

### Step 1 — register a developer app

1. Go to <https://developer.schwab.com/> and sign in with your
   Schwab brokerage credentials.
2. Click **My Apps** → **Add a new app**.
3. App name: anything (e.g. "Eiswein"). Description: one sentence.
4. **API products**: select **Accounts and Trading Production**.
5. **Callback URL**: enter **exactly**:
   ```
   https://localhost:8080/api/v1/broker/schwab/callback
   ```
   The trailing slash, the port, the path — all must match
   byte-for-byte or the OAuth callback fails silently.
6. Submit. The app sits in **Approved – Pending** for 1–3 business
   days. You'll get an email when it goes **Approved – Ready for
   Use**.

### Step 2 — install local certs

Schwab requires HTTPS for the callback even on `localhost`.
`mkcert` generates a self-signed cert pair that Chrome trusts (after
a one-time root install).

```sh
# macOS
brew install mkcert nss

# Debian / Ubuntu
sudo apt install libnss3-tools
# then install mkcert binary per https://github.com/FiloSottile/mkcert/releases
```

### Step 3 — re-run the wizard

```sh
make install
```

Answer **yes** to the Schwab question. The wizard will:

- Run `mkcert -install` (adds the mkcert root to your system trust
  store — one-time, browser will trust localhost certs going forward).
- Run `mkcert localhost 127.0.0.1` and drop the pair into `certs/`.
- Print the exact redirect URI you should have registered with
  Schwab (cross-check vs. step 1.5 above).
- Ask for **Client ID** and **Client Secret** — copy from your
  Schwab developer app's detail page.

### Step 4 — connect

```sh
make start
```

The container now serves over HTTPS. Open
<https://localhost:8080>, log in, go to **設定 → 連接 Schwab**, click
**Connect**. You'll bounce to Schwab's login page → authorize → land
back at Eiswein with positions populated.

### Troubleshooting Schwab

**"Cookie not present" / 401 on /broker/schwab/start.** You navigated
to the app via a hostname other than `localhost:8080`. Schwab's
registered redirect URI pins the cookie to that exact origin. Either
update the redirect URI with Schwab (and re-run bootstrap to match)
or always use `https://localhost:8080`.

**"State mismatch" on callback.** The CSRF nonce cookie that
`/broker/schwab/start` set didn't survive the round-trip. Almost
always caused by clearing cookies mid-flow or using two browser tabs
at the same time on different hostnames. Re-click Connect from a
single tab.

**`mkcert: command not found` during bootstrap.** The wizard prints
the install command for your OS. Install mkcert, then re-run
`make install`.

**Cert pair in `certs/` but app starts over HTTP.** The entrypoint
expects exactly `certs/localhost-key.pem` + `certs/localhost.pem`. If
mkcert wrote different filenames, rename them.

---

## 4. Browser cert warning ("Not Secure")

Whether you use HTTPS (Schwab path) or HTTP (default), Chrome /
Safari will paint the URL bar with a warning the first time. This is
expected.

For HTTP `localhost:8080`, Chrome treats `localhost` as a "secure
context" anyway — the warning is purely cosmetic and `Secure` cookies
work.

For HTTPS with self-signed `mkcert`, Chrome trusts the cert once
`mkcert -install` has added the root to the system trust store. If
you see the warning anyway, click **Advanced** → **Proceed to
localhost (unsafe)** — the connection is fine, it's just that Chrome
hasn't picked up the new root for this profile yet.

---

## 5. Updating to a new release

Whenever the maintainer pushes a new version:

```sh
cd eiswein
make update
```

That's `git pull` + `docker compose build` + `docker compose up -d`.
Migrations run automatically inside the container. Your
`data/eiswein.db` survives because it's volume-mounted from the host.

If a release introduces a **new required env var**, the maintainer
will mention it in the commit / release notes. Re-run `make install`
to walk the prompts again; the wizard refuses to clobber your
existing `.env` without confirmation.

---

## 6. Where things live

```
eiswein/
├── .env                # Your secrets — bootstrap writes this. chmod 600.
├── data/               # SQLite DB + parquet cache + backups
├── certs/              # mkcert TLS pair (only if Schwab is enabled)
├── docker-compose.yml  # Stack definition
├── README.md / README_zhTW.md
├── docs/
│   └── SETUP_GUIDE.md / SETUP_GUIDE_zhTW.md     ← you are here
├── scripts/
│   ├── bootstrap.py    # The make install wizard
│   ├── entrypoint.sh   # Container boot script
│   ├── uninstall.sh    # Destructive cleanup
│   └── set_password.py # Standalone bcrypt hash generator
└── Makefile
```

---

## 7. Asking for help

This is a private repo with a tiny user base. If you hit something
that this guide doesn't cover:

- Skim `make logs` — almost every issue logs a structured line with
  the cause.
- DM the maintainer with the relevant log line (please trim any
  Schwab tokens before sharing).
