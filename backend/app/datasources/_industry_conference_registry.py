"""Hardcoded registry of well-known tech industry conferences.

This is the deterministic input to :class:`GeminiIndustrySource` — the
LLM is given a curated list of conferences and asked to find each one's
next confirmed date. Keeping the list in code (rather than a YAML file)
makes the surface area reviewable in pull requests; a runaway LLM can't
invent events outside this set.

Adding a conference = appending a tuple entry below. The ``primary_ticker``
field is used by the calendar UI's per-ticker catalyst chip — set it
only when the event meaningfully moves one specific stock (e.g. WWDC →
AAPL, GTC → NVDA). For broader industry events leave it None.

The ``typical_window`` field is passed to the LLM as a hint to anchor
its search ("WWDC is typically the first week of June"). This drastically
reduces hallucination — without it the LLM might confuse WWDC with
another Apple event.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class ConferenceSource(NamedTuple):
    """One conference Gemini will look up each weekly sync."""

    name: str
    organizer: str
    typical_window: str
    tags: tuple[str, ...]
    primary_ticker: str | None


# Order is preserved into the prompt; group by industry vertical so the
# LLM has consistent context blocks rather than thrashing between topics.
CONFERENCES: Final[tuple[ConferenceSource, ...]] = (
    # --- 半導體 / AI infrastructure -------------------------------------
    ConferenceSource(
        name="NVIDIA GTC (Spring / San Jose)",
        organizer="NVIDIA",
        typical_window="mid-March, San Jose Convention Center",
        tags=("Semis", "AI"),
        primary_ticker="NVDA",
    ),
    ConferenceSource(
        name="NVIDIA GTC (Fall / DC or virtual)",
        organizer="NVIDIA",
        typical_window="October, Washington DC or virtual",
        tags=("Semis", "AI"),
        primary_ticker="NVDA",
    ),
    ConferenceSource(
        name="Computex Taipei",
        organizer="TAITRA",
        typical_window="late May / early June, Taipei Nangang",
        tags=("Semis", "Hardware"),
        primary_ticker=None,
    ),
    ConferenceSource(
        name="Hot Chips Symposium",
        organizer="IEEE / Stanford",
        typical_window="late August, Stanford University",
        tags=("Semis",),
        primary_ticker=None,
    ),
    ConferenceSource(
        name="SC (Supercomputing Conference)",
        organizer="ACM / IEEE",
        typical_window="mid-November, US host city rotates",
        tags=("HPC", "AI"),
        primary_ticker=None,
    ),
    ConferenceSource(
        name="AMD Advancing AI",
        organizer="AMD",
        typical_window="annual, usually Q4",
        tags=("Semis", "AI"),
        primary_ticker="AMD",
    ),
    ConferenceSource(
        name="Intel Vision",
        organizer="Intel",
        typical_window="April / May, US",
        tags=("Semis",),
        primary_ticker="INTC",
    ),
    # --- 消費電子 / 平台 ------------------------------------------------
    ConferenceSource(
        name="CES (Consumer Electronics Show)",
        organizer="CTA",
        typical_window="first full week of January, Las Vegas",
        tags=("ConsumerElectronics",),
        primary_ticker=None,
    ),
    ConferenceSource(
        name="Apple WWDC Keynote",
        organizer="Apple",
        typical_window="first or second Monday of June, Apple Park",
        tags=("AI", "Hardware"),
        primary_ticker="AAPL",
    ),
    ConferenceSource(
        name="Apple September Event",
        organizer="Apple",
        typical_window="second Tuesday of September, Apple Park",
        tags=("Hardware",),
        primary_ticker="AAPL",
    ),
    ConferenceSource(
        name="Apple October Event",
        organizer="Apple",
        typical_window="late October, virtual (iPad / Mac refresh)",
        tags=("Hardware",),
        primary_ticker="AAPL",
    ),
    ConferenceSource(
        name="Google I/O",
        organizer="Google",
        typical_window="mid-May, Shoreline Amphitheatre Mountain View",
        tags=("AI", "Platform"),
        primary_ticker="GOOGL",
    ),
    ConferenceSource(
        name="Made by Google",
        organizer="Google",
        typical_window="August (Pixel launch)",
        tags=("Hardware",),
        primary_ticker="GOOGL",
    ),
    ConferenceSource(
        name="Samsung Galaxy Unpacked",
        organizer="Samsung",
        typical_window="early January (S series) + mid-July (Fold/Flip)",
        tags=("Hardware",),
        primary_ticker=None,
    ),
    ConferenceSource(
        name="Meta Connect",
        organizer="Meta",
        typical_window="late September",
        tags=("AI", "AR/VR"),
        primary_ticker="META",
    ),
    # --- 雲端 / 企業軟體 ------------------------------------------------
    ConferenceSource(
        name="AWS re:Invent",
        organizer="Amazon Web Services",
        typical_window="first or second week of December, Las Vegas",
        tags=("Cloud", "AI"),
        primary_ticker="AMZN",
    ),
    ConferenceSource(
        name="Microsoft Build",
        organizer="Microsoft",
        typical_window="mid-May, Seattle",
        tags=("Cloud", "AI"),
        primary_ticker="MSFT",
    ),
    ConferenceSource(
        name="Microsoft Ignite",
        organizer="Microsoft",
        typical_window="mid-November",
        tags=("Cloud", "Enterprise"),
        primary_ticker="MSFT",
    ),
    ConferenceSource(
        name="Google Cloud Next",
        organizer="Google",
        typical_window="April, Las Vegas",
        tags=("Cloud", "AI"),
        primary_ticker="GOOGL",
    ),
    ConferenceSource(
        name="Oracle CloudWorld",
        organizer="Oracle",
        typical_window="September, Las Vegas",
        tags=("Cloud", "Enterprise"),
        primary_ticker="ORCL",
    ),
    ConferenceSource(
        name="Salesforce Dreamforce",
        organizer="Salesforce",
        typical_window="September, San Francisco",
        tags=("Cloud", "Enterprise"),
        primary_ticker="CRM",
    ),
    # --- 跨產業 / 政策 --------------------------------------------------
    ConferenceSource(
        name="MWC Barcelona",
        organizer="GSMA",
        typical_window="late February / early March, Barcelona",
        tags=("Telecom", "Hardware"),
        primary_ticker=None,
    ),
    ConferenceSource(
        name="World AI Conference (WAIC) Shanghai",
        organizer="MIIT / Shanghai Municipality",
        typical_window="early July, Shanghai",
        tags=("AI",),
        primary_ticker=None,
    ),
    # --- 投資 / 總經 ----------------------------------------------------
    ConferenceSource(
        name="Berkshire Hathaway Annual Shareholder Meeting",
        organizer="Berkshire Hathaway",
        typical_window="first Saturday of May, Omaha",
        tags=("Investing",),
        primary_ticker="BRK-B",
    ),
    ConferenceSource(
        name="World Economic Forum (Davos)",
        organizer="WEF",
        typical_window="mid-January, Davos Switzerland",
        tags=("Macro", "Policy"),
        primary_ticker=None,
    ),
)


__all__ = ["CONFERENCES", "ConferenceSource"]
