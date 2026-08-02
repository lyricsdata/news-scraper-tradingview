"""A compact TradingView ticker-news dashboard for Streamlit."""

import html
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import streamlit as st

try:
    from tradingview_scraper.symbols.news import NewsScraper
except ImportError:
    NewsScraper = None


SGT = ZoneInfo("Asia/Singapore")
DEFAULT_TICKERS = "GOOG, PLTR, SPCX, AAPL"
ACCENT, TEXT, DIM, BG, PANEL, LINE = "#ffb000", "#e8d5a3", "#8a7a4d", "#0d0e0b", "#14150f", "#39351f"
# TradingView's public symbol-search endpoint is occasionally blocked by hosted
# Streamlit environments.  NASDAQ is the practical default for this app's U.S.
# equity watchlist; users can always override it with SYMBOL:EXCHANGE.
FALLBACK_EXCHANGE = "NASDAQ"

st.set_page_config(page_title="TV Ticker News", page_icon="📡", layout="wide")
st.markdown(
    f"""
    <style>
    .stApp {{background:{BG}; color:{TEXT}; font-family:Inter,Arial,sans-serif;}}
    section[data-testid="stSidebar"] {{background:{PANEL}; border-right:1px solid {LINE};}}
    h1,h2,h3 {{color:{ACCENT} !important; font-family:"Courier New",monospace;}}
    p,span,label,div {{color:{TEXT};}}
    span[data-testid="stIconMaterial"],[class*="material-symbols"] {{font-family:"Material Symbols Rounded" !important;}}
    .masthead {{border-bottom:2px solid {ACCENT}; padding-bottom:.55rem; margin-bottom:.4rem;}}
    .masthead .title {{color:{ACCENT}; font:600 1.55rem "Courier New",monospace; letter-spacing:.14em;}}
    .masthead .sub,.side-label,.news-meta {{color:{DIM} !important; font-family:"Courier New",monospace;}}
    .side-label {{font-size:.72rem; letter-spacing:.12em; margin:.9rem 0 .3rem;}}
    .news-card {{background:{PANEL}; border:1px solid {LINE}; border-left:3px solid {DIM}; border-radius:5px; padding:.85rem 1rem; margin-bottom:.65rem;}}
    .news-card:hover {{border-left-color:{ACCENT};}}
    .news-title {{color:{TEXT} !important; text-decoration:none; font-size:1.02rem; line-height:1.4;}}
    .news-title:hover {{color:{ACCENT} !important;}}
    .news-meta {{font-size:.74rem; margin-top:.45rem;}}
    .tag,.new-badge {{border:1px solid {DIM}; border-radius:3px; padding:.05rem .4rem; margin-right:.4rem;}}
    .tag {{color:{ACCENT} !important;}} .new-badge {{color:#72d6df !important; border-color:#72d6df; font-weight:bold;}}
    .summary-card {{background:{PANEL}; border:1px solid {LINE}; border-radius:5px; padding:.45rem .7rem; height:5rem; box-sizing:border-box;}}
    .summary-label {{color:{DIM} !important; font-family:"Courier New",monospace; font-size:.8rem;}}
    .summary-value {{color:{ACCENT} !important; font-family:"Courier New",monospace; font-size:1.1rem; line-height:1.2; margin-top:.18rem;}}
    .stats-spacer {{height:.85rem;}}
    @media (max-width: 640px) {{
        .summary-card {{height:4.75rem;}}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_tickers(raw: str) -> list[tuple[str, str]]:
    """Accept bare tickers, with SYMBOL:EXCHANGE retained as an override."""
    entries, seen = [], set()
    for chunk in raw.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        symbol, separator, exchange = chunk.partition(":")
        symbol, exchange = symbol.strip().upper(), exchange.strip().upper() if separator else ""
        if symbol and (symbol, exchange) not in seen:
            entries.append((symbol, exchange))
            seen.add((symbol, exchange))
    return entries


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def resolve_exchange(symbol: str) -> tuple[str, str, str]:
    """Find the best TradingView listing for a bare ticker.

    The source endpoint is intentionally isolated here: a network failure does
    not prevent explicitly supplied SYMBOL:EXCHANGE entries from working.
    """
    url = f"https://symbol-search.tradingview.com/symbol_search/?text={quote(symbol)}&hl=1&lang=en&search_type=undefined"
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=6) as response:  # noqa: S310 - fixed HTTPS host
            matches = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - a hosted deployment may block this endpoint
        return FALLBACK_EXCHANGE, "", "Market lookup unavailable; using NASDAQ."

    exact = [m for m in matches if str(m.get("symbol", "")).upper() == symbol]
    candidates = exact or matches
    candidates = [m for m in candidates if m.get("exchange")]
    if not candidates:
        return FALLBACK_EXCHANGE, "", "No listing found; using NASDAQ."

    preferred = {"NASDAQ": 0, "NYSE": 1, "AMEX": 2, "LSE": 3, "TSX": 4, "BINANCE": 5}
    candidates.sort(key=lambda m: (preferred.get(str(m.get("exchange", "")).upper(), 99), str(m.get("full_name", ""))))
    best = candidates[0]
    return str(best.get("exchange", "")).upper(), str(best.get("description", "")), ""


def resolve_entries(entries: list[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    resolved, warnings = [], []
    for symbol, supplied_exchange in entries:
        if supplied_exchange:
            resolved.append({"symbol": symbol, "exchange": supplied_exchange, "description": "", "manual": True})
            continue
        exchange, description, error = resolve_exchange(symbol)
        resolved.append({"symbol": symbol, "exchange": exchange, "description": description, "manual": False})
        if error:
            warnings.append(f"{symbol}: {error} To use another market, enter `{symbol}:EXCHANGE`.")
    return resolved, warnings


@st.cache_data(show_spinner=False, ttl=60 * 5)
def fetch_headlines(symbol: str, exchange: str, sort: str, _refresh_bucket: int) -> list[dict]:
    scraper = NewsScraper(export_result=False)
    result = scraper.scrape_headlines(symbol=symbol, exchange=exchange, sort=sort)
    return result.get("data", []) if isinstance(result, dict) else (result or [])


def format_timestamp(value) -> tuple[str, datetime | None]:
    try:
        timestamp = int(value)
        if timestamp > 10_000_000_000:  # Defensive support for milliseconds.
            timestamp //= 1000
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(SGT)
        return dt.strftime("%Y-%m-%d %H:%M SGT"), dt
    except (ValueError, OSError, TypeError):
        return str(value or ""), None


def build_article(item: dict, symbol: str, exchange: str) -> dict:
    published, published_dt = format_timestamp(item.get("published"))
    story_path = item.get("storyPath", "")
    return {
        "title": str(item.get("title") or "(no title)"),
        "provider": str(item.get("source") or item.get("provider") or ""),
        "published": published,
        "published_dt": published_dt,
        "url": str(item.get("link") or (f"https://www.tradingview.com{story_path}" if story_path else "")),
        "symbol": symbol,
        "exchange": exchange,
        "related": ", ".join(r.get("symbol", "") for r in (item.get("relatedSymbols") or []) if r.get("symbol")),
    }


def render_articles(articles: list[dict], new_urls: set[str]) -> None:
    for article in articles:
        title = html.escape(article["title"])
        url = html.escape(article["url"], quote=True)
        headline = f'<a class="news-title" href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>' if url else f'<span class="news-title">{title}</span>'
        meta = []
        if article["url"] in new_urls:
            meta.append('<span class="new-badge">NEW</span>')
        meta.append(f'<span class="tag">{html.escape(article["symbol"])} · {html.escape(article["exchange"])}</span>')
        if article["provider"]:
            meta.append(html.escape(article["provider"]))
        if article["published"]:
            meta.append(html.escape(article["published"]))
        if article["related"]:
            meta.append("related: " + html.escape(article["related"]))
        st.markdown(f'<div class="news-card">{headline}<div class="news-meta">{" · ".join(meta)}</div></div>', unsafe_allow_html=True)


st.markdown('<div class="masthead"><span class="title">TV TICKER NEWS</span><span class="sub">TradingView · ticker monitor</span></div>', unsafe_allow_html=True)

initial_tickers = st.query_params.get("tickers", DEFAULT_TICKERS)
with st.sidebar:
    if st.button("↻ REFRESH NOW", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.caption("News is cached until the selected refresh interval elapses.")
    st.markdown('<div class="side-label">Tickers</div>', unsafe_allow_html=True)
    tickers_raw = st.text_area(
        "Tickers",
        value=initial_tickers,
        height=105,
        label_visibility="collapsed",
        help="Enter AAPL, GOOG, BTCUSD, etc. The market is found automatically. Use AAPL:NASDAQ only to override it.",
    )
    st.caption("One per line or comma-separated. Market is automatic; `AAPL:NASDAQ` remains available as an override.")
    st.markdown('<div class="side-label">News options</div>', unsafe_allow_html=True)
    sort_order = st.selectbox("Sort", ["latest", "popular"], label_visibility="collapsed")
    max_items = st.slider("Max headlines per ticker", 5, 50, 15)
    ttl_minutes = st.slider("Refresh interval (minutes)", 1, 30, 5)

entries = parse_tickers(tickers_raw)
if not entries:
    st.info("Add at least one ticker, for example `AAPL, GOOG, PLTR`.")
    st.stop()

if st.query_params.get("tickers") != tickers_raw:
    st.query_params["tickers"] = tickers_raw

with st.spinner("Resolving ticker markets..."):
    resolved_entries, resolve_warnings = resolve_entries(entries)
if not resolved_entries:
    st.stop()

resolved_label = " · ".join(f"{entry['symbol']}:{entry['exchange']}" for entry in resolved_entries)
st.caption(f"Watching {resolved_label}")

refresh_bucket = int(time.time() // (ttl_minutes * 60))
articles, fetch_errors = [], []
for entry in resolved_entries:
    with st.spinner(f"Fetching {entry['symbol']} news..."):
        try:
            items = fetch_headlines(entry["symbol"], entry["exchange"], sort_order, refresh_bucket)
            articles.extend(build_article(item, entry["symbol"], entry["exchange"]) for item in items[:max_items])
        except Exception as exc:  # noqa: BLE001
            fetch_errors.append(f"{entry['symbol']}:{entry['exchange']} — {type(exc).__name__}: {exc}")
for error in fetch_errors:
    st.error(f"Could not fetch news for {error}")
if not articles:
    st.info("No news returned. Try Refresh now, another ticker, or an explicit `SYMBOL:EXCHANGE` entry.")
    st.stop()

articles.sort(key=lambda item: item["published_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
current_urls = {article["url"] for article in articles if article["url"]}
prior_urls = st.session_state.get("seen_news_urls")
new_urls = current_urls - prior_urls if prior_urls is not None else set()
st.session_state.seen_news_urls = current_urls

c1, c2, c3 = st.columns(3)
def render_summary_card(column, label: str, value: str) -> None:
    column.markdown(
        f'<div class="summary-card"><div class="summary-label">{label}</div>'
        f'<div class="summary-value">{value}</div></div>',
        unsafe_allow_html=True,
    )


render_summary_card(c1, "ARTICLES", str(len(articles)))
render_summary_card(c2, "TICKERS", str(len(resolved_entries)))
fetched_at = datetime.now(SGT).strftime("%Y-%m-%d<br>%H:%M")
render_summary_card(c3, "LAST FETCHED (SGT)", fetched_at)
st.markdown('<div class="stats-spacer"></div>', unsafe_allow_html=True)

filter_a, filter_b, filter_c = st.columns([2, 2, 3])
with filter_a:
    ticker_filter = st.selectbox("Ticker", ["All tickers"] + [f"{e['symbol']}:{e['exchange']}" for e in resolved_entries], label_visibility="collapsed")
with filter_b:
    providers = sorted({article["provider"] for article in articles if article["provider"]})
    provider_filter = st.selectbox("Source", ["All sources"] + providers, label_visibility="collapsed")
with filter_c:
    search_query = st.text_input("Search", placeholder="Search headlines…", label_visibility="collapsed")

age_filter = st.radio("Date range", ["All time", "Past 24 hours", "Past 7 days"], horizontal=True, label_visibility="collapsed")
filtered = articles
if ticker_filter != "All tickers":
    filtered = [a for a in filtered if f"{a['symbol']}:{a['exchange']}" == ticker_filter]
if provider_filter != "All sources":
    filtered = [a for a in filtered if a["provider"] == provider_filter]
if search_query.strip():
    filtered = [a for a in filtered if search_query.strip().lower() in a["title"].lower()]
if age_filter != "All time":
    cutoff = datetime.now(SGT) - timedelta(hours=24 if age_filter == "Past 24 hours" else 24 * 7)
    filtered = [a for a in filtered if a["published_dt"] and a["published_dt"] >= cutoff]

tab_names = ["ALL"] + [f"{e['symbol']} ({e['exchange']})" for e in resolved_entries]
tabs = st.tabs(tab_names)
with tabs[0]:
    st.caption(f"Showing {len(filtered)} of {len(articles)} headlines")
    render_articles(filtered, new_urls)
for tab, entry in zip(tabs[1:], resolved_entries):
    with tab:
        ticker_articles = [a for a in filtered if a["symbol"] == entry["symbol"] and a["exchange"] == entry["exchange"]]
        st.caption(f"{len(ticker_articles)} headline(s)")
        if ticker_articles:
            render_articles(ticker_articles, new_urls)
        else:
            st.info("No headlines match the current filters.")
