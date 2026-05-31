#!/usr/bin/env python3
"""Interactive bootstrap for the distributable Eiswein image.

What this script does:

1. Checks the local environment (Docker, git remote, optional mkcert).
2. Generates the always-secret values (JWT_SECRET, ENCRYPTION_KEY).
3. Asks for the admin username + password and hashes the password
   with bcrypt-12.
4. Walks the operator through the optional integrations — FRED API
   key (for macro indicators), SMTP (Gmail App Password or local
   Mailpit), Schwab broker (with self-signed TLS via mkcert).
5. Writes the assembled values to ``.env`` in the repo root.

The script is **idempotent in spirit** — running it twice overwrites
``.env`` from scratch. It refuses to clobber an existing ``.env``
without explicit confirmation, so an accidental re-run can't wipe a
working setup.

Normally invoked via ``make install`` (which manages a private
``.venv-bootstrap/`` so bcrypt + zxcvbn never touch the operator's
system Python). Calling this script directly assumes those deps are
already importable.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import os
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
ENV_PATH: Final[Path] = REPO_ROOT / ".env"
CERTS_DIR: Final[Path] = REPO_ROOT / "certs"
MIN_PASSWORD_LEN: Final[int] = 16
MIN_ZXCVBN_SCORE: Final[int] = 3

# Host port mapped to the container in docker-compose.yml. Kept here
# as a constant so any future port change has one place to update.
HOST_PORT: Final[int] = 8080


def _ensure_deps() -> tuple[object, object]:
    """Import the optional deps lazily so the script can show a clean
    install hint instead of a Python traceback when they're missing."""
    try:
        import bcrypt  # type: ignore[import-untyped]
        from zxcvbn import zxcvbn  # type: ignore[import-untyped]
    except ImportError:
        print(
            "Bootstrap needs `bcrypt` and `zxcvbn`. The supported install\n"
            "path is via `make install`, which sets up a private venv\n"
            "(.venv-bootstrap/) for you. To recover from a manual run:\n"
            "    make install\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return bcrypt, zxcvbn


# ---------- Prompt helpers ---------------------------------------------------


def _prompt(message: str, *, default: str | None = None) -> str:
    """Plain text prompt with optional default."""
    suffix = f" [{default}]" if default else ""
    raw = input(f"{message}{suffix}: ").strip()
    if not raw and default is not None:
        return default
    return raw


def _prompt_yes_no(message: str, *, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        raw = input(f"{message}{suffix}: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _prompt_password(bcrypt_mod: object, zxcvbn_mod: object) -> str:
    """Prompt twice, validate strength, return the bcrypt hash.

    Defensive against three real-world copy/paste foot-guns we've
    actually hit:

    1. Trailing newline / whitespace from clipboard. Stripped silently;
       the user's intended password almost never ends with a space, and
       the resulting hash needs to round-trip against the cleanly-typed
       login form.
    2. macOS smart-quote substitution. ``"`` / ``"`` / ``'`` / ``'``
       get folded back to ASCII ``"`` / ``'`` before hashing AND a
       warning is printed so the operator knows to type ASCII at the
       login form.
    3. Non-printable / control characters anywhere in the password —
       almost always an artefact of pasting from a rich-text source;
       refuse the entry and ask again rather than silently strip.
    """
    while True:
        first_raw = getpass.getpass("Admin password: ")
        second_raw = getpass.getpass("Confirm password: ")

        # Strip surrounding whitespace; flag if we had to.
        first = first_raw.strip()
        second = second_raw.strip()
        if first != first_raw or second != second_raw:
            print(
                "  ℹ Surrounding whitespace was stripped from the pasted "
                "password — the hash is for the trimmed value."
            )

        # Normalise smart quotes → ASCII so login-form typing matches.
        normalised_first = _normalise_quotes(first)
        if normalised_first != first:
            print(
                "  ⚠ Smart-quote characters were converted to ASCII (\" / '). "
                "Type ASCII quotes at the login form."
            )
            first = normalised_first
            second = _normalise_quotes(second)

        # Refuse control / non-printable chars — almost always a paste
        # artefact and impossible to retype reliably.
        bad = _find_unprintable(first)
        if bad is not None:
            print(
                f"  ✗ Password contains a non-printable character (U+{bad:04X}). "
                "Likely a rich-text paste — try again with plain text."
            )
            continue

        if first != second:
            print("Passwords do not match — try again.")
            continue
        if len(first) < MIN_PASSWORD_LEN:
            print(
                f"Password must be at least {MIN_PASSWORD_LEN} characters "
                "(or use a long passphrase)."
            )
            continue
        strength = zxcvbn_mod(first)  # type: ignore[operator]
        if int(strength.get("score", 0)) < MIN_ZXCVBN_SCORE:
            feedback = strength.get("feedback", {}) or {}
            warning = feedback.get("warning") or "password is too guessable"
            print(f"Weak password — {warning}")
            for suggestion in feedback.get("suggestions") or []:
                print(f"  • {suggestion}")
            continue
        hashed = bcrypt_mod.hashpw(  # type: ignore[attr-defined]
            first.encode("utf-8"),
            bcrypt_mod.gensalt(rounds=12),  # type: ignore[attr-defined]
        )
        return hashed.decode("utf-8")


_SMART_QUOTE_MAP: Final[dict[str, str]] = {
    "“": '"',  # LEFT DOUBLE QUOTATION MARK
    "”": '"',  # RIGHT DOUBLE QUOTATION MARK
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "’": "'",  # RIGHT SINGLE QUOTATION MARK
    "–": "-",  # EN DASH (macOS auto-replace)
    "—": "-",  # EM DASH
}


def _normalise_quotes(value: str) -> str:
    """Replace macOS auto-substituted smart quotes / dashes with their
    ASCII equivalents so the login-form (no auto-substitution) input
    matches the bootstrap-time input."""
    if not any(ch in value for ch in _SMART_QUOTE_MAP):
        return value
    return "".join(_SMART_QUOTE_MAP.get(ch, ch) for ch in value)


def _find_unprintable(value: str) -> int | None:
    """Return the codepoint of the first non-printable / control
    character in ``value``, or ``None`` if all chars are printable.

    Used to refuse passwords that obviously came from a rich-text
    paste (zero-width spaces, BIDI marks, NULs) since the user would
    have no way to retype them at the login form.
    """
    for ch in value:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            return code
        # U+200B-U+200D zero-width chars + U+FEFF BOM are the usual
        # invisible-paste suspects.
        if code in (0x200B, 0x200C, 0x200D, 0xFEFF):
            return code
    return None


# ---------- Environment checks ----------------------------------------------


def _check_docker() -> None:
    if shutil.which("docker") is None:
        print(
            "Docker isn't on $PATH. Install Docker Desktop\n"
            "(https://www.docker.com/products/docker-desktop/),\n"
            "open the app once so it links the CLI, and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    # Docker CLI is present — also verify the Compose v2 plugin works.
    # `make start` / `make stop` / `make update` all run `docker compose
    # …`, which silently fails with "unknown shorthand flag" if the
    # plugin is missing. Catching it here gives a clear remediation
    # instead of an opaque docker error 60 seconds later.
    version_output = _query_compose_version()
    if version_output is not None:
        print(f"  ✓ Docker found ({version_output.strip()})")
        return

    # Docker CLI works but the plugin isn't on its search path. The
    # most common cause on a Homebrew Mac is that the user installed
    # `brew install docker-compose` (which drops the plugin into
    # /opt/homebrew/lib/docker/cli-plugins/) without telling the
    # Docker CLI to look there. Probe + auto-patch.
    if _try_link_homebrew_compose_plugin():
        version_output = _query_compose_version()
        if version_output is not None:
            print(f"  ✓ Docker found ({version_output.strip()}) — linked Homebrew plugin")
            return

    print(
        "Docker is installed but the Compose v2 plugin is missing.\n"
        "`make start` requires `docker compose` (not the legacy\n"
        "`docker-compose` v1).\n"
        "\n"
        "Fix:\n"
        "  1. Open Docker Desktop and wait for the menu-bar whale\n"
        "     to say 'Docker Desktop is running'. Re-run install.\n"
        "  2. If that doesn't help, install the plugin manually:\n"
        "       brew install docker-compose\n"
        "     (Despite the name, this is the Compose v2 plugin.\n"
        "     Bootstrap will auto-link it into ~/.docker/config.json\n"
        "     on the next run.)\n"
        "  3. As a last resort: brew reinstall --cask docker.\n",
        file=sys.stderr,
    )
    sys.exit(1)


def _query_compose_version() -> str | None:
    """Run `docker compose version` and return stdout on success.

    Returns ``None`` when the plugin isn't found OR the command times
    out. Never raises — callers branch on the return value.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["docker", "compose", "version"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    if "Compose version" not in result.stdout:
        return None
    return result.stdout


# Standard Homebrew Compose plugin location on Apple Silicon. Intel
# Homebrew uses /usr/local/lib/docker/cli-plugins; we probe both.
_HOMEBREW_COMPOSE_PLUGIN_DIRS: Final[tuple[Path, ...]] = (
    Path("/opt/homebrew/lib/docker/cli-plugins"),
    Path("/usr/local/lib/docker/cli-plugins"),
)
_DOCKER_CONFIG_PATH: Final[Path] = Path.home() / ".docker" / "config.json"


def _try_link_homebrew_compose_plugin() -> bool:
    """Patch ``~/.docker/config.json`` to include the Homebrew Compose
    plugin directory in ``cliPluginsExtraDirs``.

    Returns True iff a plugin binary was found AND the config now
    references its directory. Safe to call repeatedly — existing
    ``cliPluginsExtraDirs`` entries are preserved; the function only
    appends missing paths. If no plugin binary lives in any
    Homebrew-standard location, the function is a no-op and returns
    False so the caller can fall through to the user-facing error.
    """
    plugin_dir: Path | None = None
    for candidate in _HOMEBREW_COMPOSE_PLUGIN_DIRS:
        if (candidate / "docker-compose").exists():
            plugin_dir = candidate
            break
    if plugin_dir is None:
        return False

    import json  # local import — only needed on this slow path.

    _DOCKER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _DOCKER_CONFIG_PATH.exists():
        try:
            existing = json.loads(_DOCKER_CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, json.JSONDecodeError):
            # Corrupt or unreadable config — surface to the user
            # rather than silently overwriting whatever they had.
            print(
                f"  ⚠ {_DOCKER_CONFIG_PATH} exists but isn't valid JSON. "
                "Skipping auto-link; please fix it by hand."
            )
            return False
    else:
        existing = {}

    extra_dirs_raw = existing.get("cliPluginsExtraDirs", [])
    extra_dirs: list[str] = (
        list(extra_dirs_raw) if isinstance(extra_dirs_raw, list) else []
    )
    plugin_str = str(plugin_dir)
    if plugin_str not in extra_dirs:
        extra_dirs.append(plugin_str)
    existing["cliPluginsExtraDirs"] = extra_dirs
    _DOCKER_CONFIG_PATH.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  → linked {plugin_dir} into {_DOCKER_CONFIG_PATH}")
    return True


def _check_git_remote() -> None:
    try:
        # Fixed argv + PATH lookup is exactly what this boot wizard
        # wants — ruff's bandit rules flag it defensively.
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            "  ⚠ git origin remote not set — `make update` will fail until "
            "you `git remote add origin <url>`",
        )
        return
    print(f"  ✓ git origin → {result.stdout.strip()}")


def _check_mkcert(install_hint: bool) -> bool:
    if shutil.which("mkcert") is not None:
        print("  ✓ mkcert found")
        return True
    if install_hint:
        print(
            "  ⚠ mkcert not found. Install with:\n"
            "      macOS:   brew install mkcert nss\n"
            "      Linux:   apt install mkcert  (or build from source)\n"
            "    Then re-run bootstrap."
        )
    return False


# ---------- Secret generation ------------------------------------------------


def _gen_jwt_secret() -> str:
    return secrets.token_urlsafe(64)


def _gen_encryption_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


# ---------- Section workflows ------------------------------------------------


def _section_admin(bcrypt_mod: object, zxcvbn_mod: object) -> dict[str, str]:
    print("\n[Admin login]")
    username = _prompt("Admin username", default="admin")
    password_hash = _prompt_password(bcrypt_mod, zxcvbn_mod)
    return {
        "ADMIN_USERNAME": username,
        "ADMIN_PASSWORD_HASH": password_hash,
    }


# Trading-day presets for the backfill-window prompt. Keys are the
# UI labels; values are the literal integer the operator picks.
# ``300`` is the default (covers all 12 indicators with safety margin);
# the deeper options unlock longer history charts and back-testing-style
# context on the History page.
_BACKFILL_PRESETS: Final[dict[str, int]] = {
    "1": 300,   # ~14 months (default, fast install)
    "2": 504,   # ~2 years
    "3": 1260,  # ~5 years (deepest — matches the chart 'ALL' button)
}


def _section_backfill() -> dict[str, str]:
    print("\n[Historical data depth]")
    print(
        "  Pick how far back to fetch price history on first install. All\n"
        "  12 indicators only need ~300 trading days to compute; deeper\n"
        "  windows give the History page + chart 'ALL' button more to\n"
        "  show. After install, steady-state daily updates only fetch the\n"
        "  newest bar — depth is a one-time cost.\n"
        "\n"
        "    1)  ~14 months  (default, fastest — covers all indicators)\n"
        "    2)   ~2 years   (more History-page context)\n"
        "    3)   ~5 years   (best for year-over-year pattern lookups)\n"
        "\n"
        "  Can be changed later: `make backfill DAYS=<n>` (max 1260),\n"
        "  or edit BACKFILL_WINDOW_TRADING_DAYS in .env + restart."
    )
    choice = _prompt("Choice [1-3]", default="1").strip()
    days = _BACKFILL_PRESETS.get(choice, _BACKFILL_PRESETS["1"])
    if choice not in _BACKFILL_PRESETS:
        print(f"  ⚠ unrecognised choice {choice!r} — defaulting to 14 months")
    print(f"  ✓ backfill window set to {days} trading days")
    return {"BACKFILL_WINDOW_TRADING_DAYS": str(days)}


def _section_fred() -> dict[str, str]:
    print("\n[FRED — macro indicators (VIX, yield curve, CPI, ...)]")
    if not _prompt_yes_no("Enable macro indicators?", default=True):
        return {"FRED_API_KEY": ""}
    print(
        "  FRED API keys are free. Sign up:\n"
        "    https://fred.stlouisfed.org/docs/api/api_key.html\n"
        "  (Press Enter to skip — you can paste the key into .env later.)"
    )
    return {"FRED_API_KEY": _prompt("FRED API key", default="")}


def _section_smtp() -> dict[str, str]:
    print("\n[Email reminders (optional)]")
    if not _prompt_yes_no("Enable email reminders?", default=False):
        return _empty_smtp_block()
    print(
        "  Pick a backend:\n"
        "    g) Gmail with an App Password (delivers real mail)\n"
        "    m) Local Mailpit container (catches mail for preview only)\n"
        "    s) Skip — edit .env later"
    )
    choice = _prompt("Choice [g/m/s]", default="s").lower()
    if choice.startswith("g"):
        return _section_smtp_gmail()
    if choice.startswith("m"):
        return _section_smtp_mailpit()
    return _empty_smtp_block()


def _section_smtp_gmail() -> dict[str, str]:
    print(
        "  Generate an App Password (Gmail account needs 2FA):\n"
        "    https://myaccount.google.com/apppasswords"
    )
    username = _prompt("Gmail address")
    password = getpass.getpass("Gmail App Password (16 chars, no spaces): ").strip()
    sender = _prompt("From address", default=username)
    recipient = _prompt("Send digests to", default=username)
    return {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": username,
        "SMTP_PASSWORD": password,
        "SMTP_FROM": sender,
        "SMTP_TO": recipient,
        "SMTP_STARTTLS": "true",
    }


def _section_smtp_mailpit() -> dict[str, str]:
    print(
        "  Mailpit captures outbound mail in a local web UI at "
        "http://localhost:8025.\n"
        "  IMPORTANT: start with the email profile enabled:\n"
        "    COMPOSE_PROFILES=email make start"
    )
    return {
        "SMTP_HOST": "mailpit",
        "SMTP_PORT": "1025",
        "SMTP_USERNAME": "",
        "SMTP_PASSWORD": "",
        "SMTP_FROM": "eiswein@localhost",
        "SMTP_TO": _prompt("Recipient for previews", default="me@localhost"),
        "SMTP_STARTTLS": "false",
    }


def _empty_smtp_block() -> dict[str, str]:
    return {
        "SMTP_HOST": "",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "",
        "SMTP_PASSWORD": "",
        "SMTP_FROM": "",
        "SMTP_TO": "",
        "SMTP_STARTTLS": "true",
    }


def _section_schwab() -> dict[str, str]:
    print("\n[Schwab broker integration (optional)]")
    if not _prompt_yes_no(
        "Connect your Schwab brokerage account (read-only positions)?",
        default=False,
    ):
        return _empty_schwab_block()

    mkcert_ok = _check_mkcert(install_hint=True)
    if not mkcert_ok:
        print(
            "  Skipping Schwab config — re-run bootstrap after installing mkcert."
        )
        return _empty_schwab_block()

    _ensure_certs_dir()
    _generate_local_certs()

    redirect_uri = f"https://localhost:{HOST_PORT}/api/v1/broker/schwab/callback"
    print(
        "\n  Register a Schwab Developer app at:\n"
        "    https://developer.schwab.com/\n"
        f"  Set the redirect URI exactly to:\n"
        f"    {redirect_uri}\n"
        "  Then paste the client credentials below."
    )
    client_id = _prompt("Schwab Client ID")
    client_secret = getpass.getpass("Schwab Client Secret: ").strip()

    return {
        "SCHWAB_CLIENT_ID": client_id,
        "SCHWAB_CLIENT_SECRET": client_secret,
        "SCHWAB_REDIRECT_URI": redirect_uri,
    }


def _empty_schwab_block() -> dict[str, str]:
    return {
        "SCHWAB_CLIENT_ID": "",
        "SCHWAB_CLIENT_SECRET": "",
        "SCHWAB_REDIRECT_URI": (
            f"https://localhost:{HOST_PORT}/api/v1/broker/schwab/callback"
        ),
    }


def _ensure_certs_dir() -> None:
    CERTS_DIR.mkdir(parents=True, exist_ok=True)


def _generate_local_certs() -> None:
    """Run mkcert to write a localhost cert pair into ./certs/."""
    key_path = CERTS_DIR / "localhost-key.pem"
    cert_path = CERTS_DIR / "localhost.pem"
    if key_path.exists() and cert_path.exists():
        print(f"  ✓ Existing cert pair found at {CERTS_DIR}")
        return
    print(f"  Generating self-signed TLS cert in {CERTS_DIR}/ ...")
    subprocess.run(  # noqa: S603
        ["mkcert", "-install"],  # noqa: S607
        check=False,
    )
    subprocess.run(  # noqa: S603
        [  # noqa: S607 — PATH lookup of mkcert is intentional
            "mkcert",
            "-cert-file",
            str(cert_path),
            "-key-file",
            str(key_path),
            "localhost",
            "127.0.0.1",
        ],
        cwd=CERTS_DIR,
        check=True,
    )
    print(f"  ✓ Wrote {cert_path.name} + {key_path.name}")


# ---------- .env writer ------------------------------------------------------


def _write_env(values: dict[str, str]) -> None:
    """Compose the final .env from the assembled key/value pairs."""
    body = _render_env(values)
    ENV_PATH.write_text(body, encoding="utf-8")
    # Non-POSIX filesystems (some Windows mounts) ignore chmod — not
    # worth aborting the install over.
    with contextlib.suppress(OSError):
        ENV_PATH.chmod(0o600)


def _render_env(values: dict[str, str]) -> str:
    sections: list[tuple[str, Iterable[str]]] = [
        (
            "Security",
            ["JWT_SECRET", "ENCRYPTION_KEY"],
        ),
        (
            "Admin",
            ["ADMIN_USERNAME", "ADMIN_PASSWORD_HASH"],
        ),
        (
            "Environment",
            ["ENVIRONMENT", "LOG_LEVEL", "DATABASE_URL"],
        ),
        (
            "Historical backfill",
            ["BACKFILL_WINDOW_TRADING_DAYS"],
        ),
        (
            "Data sources",
            ["FRED_API_KEY"],
        ),
        (
            "Schwab (optional)",
            [
                "SCHWAB_CLIENT_ID",
                "SCHWAB_CLIENT_SECRET",
                "SCHWAB_REDIRECT_URI",
            ],
        ),
        (
            "SMTP (optional)",
            [
                "SMTP_HOST",
                "SMTP_PORT",
                "SMTP_USERNAME",
                "SMTP_PASSWORD",
                "SMTP_FROM",
                "SMTP_TO",
                "SMTP_STARTTLS",
            ],
        ),
        (
            "Frontend / cookies",
            ["FRONTEND_URL", "COOKIE_SECURE"],
        ),
    ]

    out: list[str] = [
        "# Eiswein .env — generated by scripts/bootstrap.py",
        "# Edit by hand to tweak; re-run `make install` to regenerate.",
        "# DO NOT commit this file.",
        "",
    ]
    for title, keys in sections:
        out.append(f"# === {title} ===")
        for key in keys:
            value = values.get(key, "")
            out.append(f"{key}={value}")
        out.append("")
    return "\n".join(out)


# ---------- Main flow --------------------------------------------------------


def _assemble_defaults() -> dict[str, str]:
    """Static defaults that fall through unchanged for every install."""
    return {
        "ENVIRONMENT": "production",
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": "sqlite:///./data/eiswein.db",
        "FRONTEND_URL": f"http://localhost:{HOST_PORT}",
        # COOKIE_SECURE must match the URL scheme the browser actually
        # uses — set Secure=true on a plain http:// page and the browser
        # silently refuses the cookie, breaking login. The default below
        # matches the default FRONTEND_URL (http://localhost). The
        # Schwab branch flips both to HTTPS when mkcert certs land.
        #
        # If you later put this behind Cloudflare Tunnel (HTTPS at the
        # edge), flip COOKIE_SECURE=true AND FRONTEND_URL=https://...
        # in .env by hand.
        "COOKIE_SECURE": "false",
    }


def _confirm_overwrite() -> None:
    if not ENV_PATH.exists():
        _warn_if_stale_db_exists()
        return
    print(
        f"\n⚠ {ENV_PATH.name} already exists. Re-running bootstrap will "
        "OVERWRITE it.\n"
        "  Existing admin password, secrets, and Schwab credentials will be "
        "replaced with the values you enter next."
    )
    if not _prompt_yes_no("Continue?", default=False):
        print("Aborted — no changes made.")
        sys.exit(0)
    _warn_if_stale_db_exists()


_DB_PATH: Final[Path] = REPO_ROOT / "data" / "eiswein.db"


def _warn_if_stale_db_exists() -> None:
    """If a DB from a previous install survives, the admin row inside it
    will outlive the .env we're about to write — and the new password
    hash in .env will be ignored at first boot. Offer to delete the DB
    so the seed runs cleanly against the fresh .env.

    This is the single most confusing footgun a re-install hits:
    everything appears successful, the .env contains the new hash, but
    login fails because the container reads the admin row from the
    stale DB.
    """
    if not _DB_PATH.exists():
        return
    print(
        f"\n⚠ {_DB_PATH.relative_to(REPO_ROOT)} already exists from a "
        "previous install.\n"
        "  The admin row inside that DB will OUTLIVE the new password "
        "you're about to set.\n"
        "  At first boot, the container reads the admin row from the DB "
        "and IGNORES the new .env hash.\n"
        "\n"
        "  • Wipe the DB → fresh admin from the new .env (loses any "
        "watchlist / signal history in that DB)\n"
        "  • Keep the DB → your new password will NOT work; you'll need "
        "scripts/reset_password_offline.py to update the stored hash"
    )
    if _prompt_yes_no("Wipe data/ now so the new password takes effect?", default=True):
        import shutil as _shutil  # local — only on this branch

        data_dir = REPO_ROOT / "data"
        certs_dir = REPO_ROOT / "certs"
        for path in (data_dir, certs_dir):
            if path.is_dir():
                _shutil.rmtree(path)
                print(f"  ✓ removed {path.relative_to(REPO_ROOT)}/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Eiswein for local use.")
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip Docker / git / mkcert presence checks (advanced use only).",
    )
    args = parser.parse_args()

    print("┌──────────────────────────────────────────────┐")
    print("│       Eiswein — first-time setup wizard      │")
    print("└──────────────────────────────────────────────┘\n")

    if not args.skip_checks:
        print("[Environment checks]")
        _check_docker()
        _check_git_remote()
        print()

    bcrypt_mod, zxcvbn_mod = _ensure_deps()

    _confirm_overwrite()

    values: dict[str, str] = _assemble_defaults()
    values["JWT_SECRET"] = _gen_jwt_secret()
    values["ENCRYPTION_KEY"] = _gen_encryption_key()
    values.update(_section_admin(bcrypt_mod, zxcvbn_mod))
    values.update(_section_backfill())
    values.update(_section_fred())
    values.update(_section_smtp())
    schwab_values = _section_schwab()
    values.update(schwab_values)
    # If Schwab certs were generated, switch the runtime to HTTPS-aware cookies.
    if schwab_values["SCHWAB_CLIENT_ID"]:
        values["COOKIE_SECURE"] = "true"
        values["FRONTEND_URL"] = f"https://localhost:{HOST_PORT}"

    _write_env(values)

    print("\n┌──────────────────────────────────────────────┐")
    print(f"│  Wrote {ENV_PATH.relative_to(REPO_ROOT)} (chmod 600)                       │")
    print("└──────────────────────────────────────────────┘\n")
    print("Next steps:")
    print("  make start              # boot in the background")
    print(f"  open http://localhost:{HOST_PORT}   # (https:// if Schwab certs)")
    print("  make logs               # tail logs")
    print("  make stop               # stop the stack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
