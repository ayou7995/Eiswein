# Sherry Trading System — Condensed Reference

Eiswein is inspired by Heaton's "Sherry" trading system. This document summarizes the key concepts from a 9-article Chinese-language series by Heaton, for context when designing Eiswein's indicator logic and signal rules.

## Philosophy

- Sherry is a **systematic signal generator** used in a **quantamental** workflow (system outputs + human judgment on macro/geopolitics).
- It is **not** fully automated trading. Heaton reads signals + current news/context, then decides manually.
- ~30 indicators, ~100 strategies running in parallel. Multi-timeframe output (short/medium/long term).
- "Never a perfect scenario" — contradictions between signals are by design; disagreement is information.
- Broader knowledge (macro, political) improves signal interpretation. Pure technical reading is brittle.

## Signal System

Three colors:
- **Green (綠燈)** — bullish / buying pressure
- **Red (紅燈)** — bearish / selling pressure
- **Blue (藍燈)** — neutral / consolidation

### Core Rules (used verbatim as a starting point for Eiswein)

1. **3 consecutive greens** → likely rise (entry signal)
2. **4 consecutive reds** → sell
3. **7/10 indicators up** → "all in"
4. **Signal strength = number of agreeing indicators**
   - Many agreeing → strong conviction → larger position
   - Mixed → weak conviction → smaller position or short-term only
5. **Signals have a 1-2 day delay** — don't judge by a single day in isolation
6. **Price direction ≠ buying/selling direction**
   - Price can rise on distribution (selling) if volume/breadth is weak
   - Price can fall on accumulation (buying) if institutions are quietly building

## Accumulation / Distribution Day (A/D Day)

Adapted from William O'Neil's concept:

- **Accumulation Day**: SPX closes up AND volume is higher than previous day → institutions buying
- **Distribution Day**: SPX closes down AND volume is higher than previous day → institutions selling
- Track rolling 25-day counts
- **Key signal**: 3 accumulation days at a market low → reversal confirmation

## Bull Flag / Consolidation

- After a strong rally, tight consolidation with decreasing volume = bull flag
- Bull flag breaks: resumption of uptrend
- Bull flag fails: reversal

## Big Player Accumulation Patterns (Article 3)

Signs institutions are quietly accumulating:
- Low volatility + low volume near support
- Batch buying evidence (small but persistent green signals)
- Price holds despite broader market weakness
- Examples Heaton cited: MU, INTC, UPST, SOXL, AFRM in September 2024

## Reference Levels (as of article publication)

These are specific historical price levels mentioned by Heaton — useful only as calibration examples, not current targets:
- SPX resistance: 6600-6731 (April 2026)
- SPX support zone: 6475-6725 (also April 2026 consolidation)

## What Eiswein Simplifies

Eiswein is a personal tool, not a full Sherry reproduction. Intentional simplifications:
- **12 indicators** (not 30). Covers the same functional categories.
- **Equal-weight voting** for v1 (not learned weights). Adjust later from accumulated history.
- **Daily update cadence** (not 3x/day). User is long-term, not day trading.
- **Per-ticker focus on user's watchlist** (not full universe screening).
- **Plain-language Chinese narrative** per ticker (Sherry expects you to know how to read signals).

## Indicator Categories Eiswein Uses

| Category | Sherry approach | Eiswein equivalent |
|---|---|---|
| Trend | Multiple MAs + momentum indicators | SPX 50/200 MA, Price vs MA |
| Breadth | A/D Day + multiple breadth measures | A/D Day Count |
| Volatility | VIX + custom vol measures | VIX level + trend |
| Macro | Bond yields, rates, currency | 10Y-2Y spread, DXY, Fed Funds |
| Relative strength | Sector rotation, individual stock | Relative strength vs SPX |
| Momentum | RSI, multiple timeframes | RSI(14) + weekly RSI |
| Volume | Volume patterns, institutional flow | Volume anomaly detection |
| Timing | MACD, Bollinger Bands | MACD, Bollinger Bands |

## Key Quotes (paraphrased from articles)

> "The signal isn't magic. It's a mirror of institutional behavior. Read it with knowledge of what's happening in the world, or you'll misinterpret it."

> "Three greens doesn't mean 'go all in today.' It means 'the probability of a rise in the coming days has shifted in your favor.' Position sizing reflects that probability."

> "Never design a system that requires all indicators to agree. Market reality is contradiction. When everything agrees, you're probably at a turning point in the wrong direction."

## For Eiswein Developers

When implementing signal logic:
- Faithfully implement the 3-green / 4-red rules as defaults
- Make signal strength visible (count of agreeing indicators) — don't collapse it to binary
- Surface contradictions explicitly in the narrator output ("4 of 6 bullish, but momentum divergent")
- Don't hide the raw numbers — the user needs them alongside the plain-language summary
