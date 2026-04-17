# Eiswein

Personal stock market decision-support tool. Analyzes a user-managed watchlist using 12 technical indicators and produces daily signal reports with entry/exit/stop-loss recommendations.

Inspired by Heaton's Sherry trading system. Positioning: systematic decision-support / quantamental advisory. **Not** automated quant trading — human makes all trading decisions.

## Status

Greenfield / in development. See `~/.claude/plans/tidy-conjuring-unicorn.md` for the implementation plan.

## Stack

- **Backend**: FastAPI (Python 3.12) + SQLite + SQLAlchemy
- **Frontend**: React + TypeScript + Tailwind CSS + TradingView Lightweight Charts
- **Deployment**: Single Docker container on Oracle Cloud Free Tier / Hetzner
- **Network**: Cloudflare Tunnel + Cloudflare Access (OAuth)

## Setup (WIP)

```bash
# Copy env template
cp .env.example .env
# Edit .env with your secrets

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
cp .env.example .env
npm install

# Dev
# Terminal 1:
cd backend && uvicorn app.main:app --reload

# Terminal 2:
cd frontend && npm run dev
```

### Frontend scripts

```bash
cd frontend
npm run dev         # Vite dev server on :5173 (proxies /api to VITE_API_URL)
npm run typecheck   # tsc --noEmit (strict mode)
npm run lint        # eslint (zero warnings allowed)
npm test            # vitest run
npm run build       # type-check + production build into dist/
```

### Frontend stack (Phase 0)

- React 18 + TypeScript strict mode + Vite 5
- Tailwind CSS 3 (dark mode via `class`, signal colors extended)
- TanStack Query 5 (server state), react-router-dom v6, react-hook-form + Zod (forms)
- react-error-boundary (page + app fallbacks)
- lightweight-charts (installed for Phase 4, not yet rendered)
- vitest + @testing-library/react + jsdom (tests)

### Frontend security invariants

- JWT is carried **only** in httpOnly Set-Cookie — never localStorage, never body
- fetch wrapper sends `credentials: 'include'` and coalesces concurrent 401s onto a single refresh call
- Every API boundary parsed with a Zod schema; failures surface as `SchemaValidationError`
- No `dangerouslySetInnerHTML` anywhere

## Architecture

```
backend/app/
├── api/          # FastAPI routes
├── db/           # SQLAlchemy models
├── datasources/  # Data source interface + implementations
├── indicators/   # 12 indicator modules
├── signals/      # Voting, entry/stop-loss, narrator
├── security/     # Auth, encryption, rate limit
├── jobs/         # Cron jobs
└── utils/        # Shared utilities

frontend/src/
├── pages/        # Route components
├── components/   # Reusable UI
├── api/          # Typed fetch wrappers + Zod schemas
├── hooks/        # Shared hooks
└── lib/          # Utilities, constants
```

## Development Conventions

See `CLAUDE.md` for the full Definition of Done and coding standards.

Code is developed using Claude Code's multi-agent orchestration:
- `backend-builder` — Backend implementation
- `frontend-builder` — Frontend implementation
- `security-auditor` — Security reviews (run after every phase)
- `test-writer` — Test coverage

## Security

Security is the #1 priority. See `CLAUDE.md` for the full security model. Highlights:
- Dual-layer auth: Cloudflare Access (OAuth) + app JWT (httpOnly cookies)
- No public ports on VM (Cloudflare Tunnel only)
- AES-256 encryption for stored broker tokens
- Rate limiting, CSP, HSTS, parameterized SQL only
- All secrets via environment variables

## License

Private / personal use.
