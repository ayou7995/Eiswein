---
name: Eiswein Trading System - Design Decisions
description: Architectural decisions made so far for the Eiswein trading system, inspired by Heaton's Sherry system. Updated as grilling progresses.
type: project
originSessionId: 53ac829a-06b7-4aff-a0a6-74e2823ce65d
---
# Eiswein Trading System - Design Decisions

## Scope (re-defined 2026-04-14)

**Eiswein v1 = personal decision-support tool**, not a full Sherry-style 100-strategy engine.

User is not trying to rebuild Sherry. User wants a tool that plays the role Sherry plays *for Heaton*: ingests data, runs a small set of indicators, and produces a readable daily report flagging entry / exit / stop-loss moments for the user's own watchlist.

Positioning: **systematic decision-support / quantamental advisory**, not quant trading.

Differences vs. original plan:
- ~10 core indicators (not ~100 strategies)
- Watchlist-focused (not full stock universe screening)
- Simple rule-based signals (not complex multi-timeframe aggregation)
- Daily readout: "market posture + what to do with my positions"
- Timeline: weeks to v1, not months

## Decided

1. **Execution model**: Signal/advisory system (not automated trading). Generates daily reports; human makes all trading decisions.
2. **Language**: Python
3. **Deployment**: Docker container on a cloud VM, triggered via cron. Local Mac for dev, cloud for prod.
4. **Scope**: Personal decision-support tool (see above).

## Decided (continued)

5. **Watchlist / universe**: User-managed, flexible watchlist (add/remove anytime). Mix of US large-cap ETFs (SPY, QQQ, IWM) + individual stocks (large-cap tech + mid/small-cap growth). Target 20-50 tickers at a time, but tool must not hard-code the list.

6. **Time frame**: Primary = long-term (months-years) + position (weeks-months). Tool also provides short-term anomaly flags (not for swing trading, but to alert on near-term volatility that affects longer-term positions). Daily update cadence is sufficient.

7. **Output model**: Multi-timeframe view per ticker — long-term trend direction, position-level entry/exit signals, short-term anomaly alerts. Daily summary = "market posture + per-ticker action items."

8. **Indicator set (12 core)**: Three layers:
   - Market regime (4): SPX 50/200 MA, A/D Day Count, VIX level+trend, 10Y-2Y yield spread
   - Per-ticker direction (4): Price vs 50/200 MA, RSI(14)+weekly RSI, volume anomaly detection, relative strength vs SPX
   - Entry/exit timing (2): MACD, Bollinger Bands — added because user wants to optimize buy/sell timing even as a long-term investor (top-down timing approach)
   - Macro backdrop (2): DXY trend, Fed Funds Rate + market expectations
   
   v2 candidates: Put/Call Ratio, Sector Rotation, Market Breadth, Insider Trading

9. **Report format** (REVISED 2026-04-16): Structured scannable UI — raw numbers + **Pros/Cons list** (🟢/🔴 bullets per indicator). NO template-based paragraph narrator (abandoned — nested if/else hell, robotic output). If rich narrative becomes necessary later, use an LLM API (Claude Haiku 4.5 / Gemini Flash) with JSON input and strict prompt — never a hand-coded template. Entry/exit timing indicators (MACD, BB) surface concrete price levels as their own dedicated UI section, not buried in prose.

10. **Data sources (Plan C)**: Swappable interface pattern.
    - Dev phase: yfinance (free) + FRED API (free)
    - Alt free: Schwab API (user has existing account, applying for API access ~2026-04-15). 7-day token refresh → system sends email reminder.
    - Production: Polygon.io ($29/mo) + FRED API
    - All sources behind a DataSource interface for easy swapping.
    - DXY: FRED or yfinance (neither Schwab nor Polygon covers it natively as index).

11. **Output**: Web dashboard (user's choice). Details TBD (framework, hosting, etc.)

12. **History / Storage**: SQLite. Store daily indicator values, per-ticker signals, market snapshots, and (optionally) user's actual trades. Essential for: signal accuracy tracking, decision journaling, historical pattern matching, indicator tuning. ~few MB/year for 50 tickers × 12 indicators.

13. **Dashboard specs**: Single-user, password-protected, mobile-friendly, interactive (click tickers, switch timeframes, history charts). Hosted on cloud VM alongside the cron job. Tech stack TBD.

14. **Signal rules**: Two-layer voting system.
    - Layer 1 (Market Posture): 4 market-regime indicators vote 🟢🟡🔴 → "進攻/正常/防守"
    - Layer 2 (Per-Ticker Action): 4 direction + 2 timing indicators per ticker → 6 action categories:
      強力買入🟢🟢, 買入等回調🟢⏳, 持有✓, 觀望👀, 減倉⚠️, 出場🔴🔴
    - Equal weight per indicator (v1). Adjust weights later based on accumulated history data.
    - Macro indicators (DXY, Fed Rate) inform context/narrative, not direct voting.

15. **Entry price recommendations**: 3 tiers per ticker:
    - 積極進場: 50MA (short-term support)
    - 理想進場: Bollinger middle band / 20MA
    - 保守進場: 200MA or Bollinger lower band
    - Default split suggestion: 30% / 40% / 30% — labeled "僅供參考", user overrides as needed.

16. **Stop-loss recommendations**: Auto-calculated per ticker:
    - Healthy trend: 200MA - 3%
    - Weakening trend: Bollinger lower band or recent low - 3%

17. **Position tracking**: v1 manual input via dashboard (ticker, shares, avg cost). Enables P&L display, stop-loss impact calculation, post-add avg cost preview. Schwab API auto-sync deferred to v2.

18. **Backtesting**: v2. v1 will pre-load 1-2 years of historical price data into SQLite for chart display, but no simulated trading backtest. Reason: indicators are well-established; real usage history more valuable than backtest; avoids overfitting risk.

19. **News/sentiment**: v2. User already does fundamental/news analysis — Eiswein v1 focuses on the technical layer the user lacks. v2 candidate: auto-aggregate news headlines for watchlist tickers (no sentiment scoring).

20. **Dashboard tech stack**:
    - Backend: FastAPI (Python) — REST JSON API, serves indicator data + CRUD for positions/watchlist
    - Frontend: React + Tailwind CSS (user is a professional SWE with React experience)
    - Charts: TradingView Lightweight Charts (open-source, built for financial data, K-line + overlay indicators)
    - Deployment: Single Docker container (FastAPI serves React build) or Docker Compose, on cloud VM
    - Auth: Simple password protection (single user)

21. **Cloud VM**: Oracle Cloud Free Tier (ARM, 24GB RAM, $0) as primary. Hetzner CX22 ($4.50/mo) as backup if Oracle signup fails.

22. **SQLite persistence**: Docker volume mount (data/ dir on host). Daily cron backup via sqlite3 .backup. Weekly sync to cloud storage for extra safety.

23. **Monorepo, single container**: Multi-stage Docker build. Stage 1: build React. Stage 2: Python + serve React static via FastAPI. No CORS, single port, simplest deployment. Split only if scale demands it later.

## All core decisions made. Ready for implementation planning.

## Core Design Principles (from Sherry articles)

- Multiple diverse strategies running simultaneously to avoid groupthink
- Daily summary consolidating all signals
- Multi-timeframe predictions: short-term, medium-term, long-term
- Confidence level for each prediction (reflects how many strategies agree)
- Signal strength reflects institutional conviction (strong = many agree, weak = mixed)
- Key rules: 3 consecutive bullish signals = likely rise, 4 consecutive bearish = sell
- Signals can have 1-2 day delay — don't judge by single day
- Price direction ≠ buying/selling direction
- ~30 indicators combined in Sherry; system uses ~100 strategies
- Signal updates ideally 3x/day (after US close, midnight Asian open, before US open)
- Never a "perfect scenario" where all indicators align — contradictions are by design
- Broader knowledge context (macro, geopolitical) improves signal interpretation
