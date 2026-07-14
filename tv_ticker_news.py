"""
TradingView Ticker News Scraper
--------------------------------
Streamlit app that pulls news headlines for one or more specific tickers
from TradingView, using the `tradingview-scraper` package (wraps TradingView's
internal news API - the same one that powers tradingview.com/symbols/*/news/).

Companion to the existing English/Japanese general news scrapers; this one
is ticker-scoped rather than provider/section-scoped.
"""

import time
from datetime import datetime, timezone

import streamlit as st

try:
    from tradingview_scraper.symbols.news import NewsScraper
except ImportError:
    NewsScraper = None


# ----------------------------------------------------------------------------
# Page config + amber terminal styling (matches existing news scraper suite)
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="TV Ticker News",
    page_icon="\U0001F4E1",
    layout="wide",
)

AMBER = "#ffb000"
AMBER_DIM = "#a86f00"
BG = "#0b0d0a"
PANEL = "#111310"

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {BG};
        color: {AMBER};
        font-family: 'Courier New', Courier, monospace;
    }}
    section[data-testid="stSidebar"] {{
        background-color: {PANEL};
        border-right: 1px solid {AMBER_DIM};
    }}
    h1, h2, h3, h4, p, span, label, div {{
        color: {AMBER} !important;
        font-family: 'Courier New', Courier, monospace !important;
    }}
    .news-card {{
        border: 1px solid {AMBER_DIM};
        background-color: {PANEL};
        padding: 12px 16px;
        margin-bottom: 10px;
        border-radius: 2px;
    }}
    .news-title {{
        font-size: 1.05rem;
        font-weight: bold;
        color: {AMBER} !important;
        text-decoration: none;
    }}
    .news-meta {{
        color: {AMBER_DIM} !important;
        font-size: 0.8rem;
        margin-top: 4px;
    }}
    a {{
        color: {AMBER} !important;
    }}
    .stTextInput input, .stSelectbox div, .stMultiSelect div {{
        background-color: {PANEL} !important;
        color: {AMBER} !important;
        border-color: {AMBER_DIM} !important;
    }}
    div.stButton > button {{
        background-color: {PANEL};
        color: {AMBER};
        border: 1px solid {AMBER};
        font-family: 'Courier New', Courier, monospace;
    }}
    div.stButton > button:hover {{
        background-color: {AMBER};
        color: {BG};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("> TV_TICKER_NEWS.exe")
st.caption("TradingView news feed, filtered to specific symbols")


# ----------------------------------------------------------------------------
# Sidebar controls
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("SYMBOLS")
    default_tickers = "AAPL:NASDAQ, TSLA:NASDAQ"
    tickers_raw = st.text_area(
        "Ticker:Exchange (one per line or comma-separated)",
        value=default_tickers,
        help="Format each entry as SYMBOL:EXCHANGE, e.g. AAPL:NASDAQ, BTCUSD:BINANCE",
        height=100,
    )

    st.header("FILTERS")
    sort_order = st.selectbox("Sort", ["latest", "popular"], index=0)
    provider_filter = st.text_input(
        "Provider filter (optional)",
        value="",
        help="e.g. reuters — leave blank for all providers",
    )
    max_items_per_symbol = st.slider("Max headlines per symbol", 5, 50, 15)

    st.header("CACHE")
    ttl_minutes = st.slider("Refresh interval (minutes)", 1, 30, 5)

    run = st.button("FETCH NEWS", use_container_width=True)


def parse_tickers(raw: str):
    entries = []
    for chunk in raw.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            symbol, exchange = chunk.split(":", 1)
        else:
            symbol, exchange = chunk, ""
        entries.append((symbol.strip().upper(), exchange.strip().upper()))
    return entries


@st.cache_data(show_spinner=False, ttl=60 * 5)
def fetch_headlines(symbol: str, exchange: str, sort: str, _ttl_bucket: int):
    """_ttl_bucket forces cache invalidation on the user-selected interval."""
    scraper = NewsScraper(export_result=False)
    kwargs = {"symbol": symbol, "sort": sort}
    if exchange:
        kwargs["exchange"] = exchange
    result = scraper.scrape_headlines(**kwargs)
    return result


def format_timestamp(ts):
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OSError, TypeError):
        return str(ts)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
if NewsScraper is None:
    st.error(
        "tradingview-scraper is not installed. Add `tradingview-scraper` to "
        "requirements.txt and redeploy."
    )
    st.stop()

if not run:
    st.info("Enter tickers in the sidebar and click FETCH NEWS.")
    st.stop()

entries = parse_tickers(tickers_raw)
if not entries:
    st.warning("No tickers parsed. Use the format SYMBOL:EXCHANGE.")
    st.stop()

ttl_bucket = int(time.time() // (ttl_minutes * 60))

tabs = st.tabs([f"{sym}" + (f" ({exch})" if exch else "") for sym, exch in entries])

for (symbol, exchange), tab in zip(entries, tabs):
    with tab:
        with st.spinner(f"Fetching news for {symbol}..."):
            try:
                result = fetch_headlines(symbol, exchange, sort_order, ttl_bucket)
            except Exception as e:  # noqa: BLE001
                st.error(f"Failed to fetch news for {symbol}: {e}")
                continue

        if not result or result.get("status") != "success":
            st.warning(f"No data returned for {symbol}.")
            continue

        items = result.get("data", [])

        if provider_filter.strip():
            pf = provider_filter.strip().lower()
            items = [it for it in items if pf in (it.get("provider", "") or "").lower()]

        items = items[:max_items_per_symbol]

        if not items:
            st.info(f"No headlines matched the current filters for {symbol}.")
            continue

        st.caption(f"{len(items)} headline(s) — sorted by {sort_order}")

        for item in items:
            title = item.get("title", "(no title)")
            provider = item.get("source") or item.get("provider", "")
            published = format_timestamp(item.get("published"))
            story_path = item.get("storyPath", "")
            link = f"https://www.tradingview.com{story_path}" if story_path else None

            related = item.get("relatedSymbols", []) or []
            related_str = ", ".join(
                r.get("symbol", "") for r in related if r.get("symbol")
            )

            title_html = (
                f'<a class="news-title" href="{link}" target="_blank">{title}</a>'
                if link
                else f'<span class="news-title">{title}</span>'
            )

            meta_bits = [b for b in [provider, published] if b]
            if related_str:
                meta_bits.append(f"related: {related_str}")
            meta_html = " · ".join(meta_bits)

            st.markdown(
                f"""
                <div class="news-card">
                    {title_html}
                    <div class="news-meta">{meta_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
