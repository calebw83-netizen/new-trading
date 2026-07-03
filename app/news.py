from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import re
from typing import Literal
from urllib.parse import quote_plus
from urllib.error import URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


NewsBias = Literal["bearish", "neutral", "bullish"]
EventRisk = Literal["low", "elevated", "extreme"]


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: str
    summary: str = ""


KEYWORDS_BY_ASSET = {
    "BTC": {"bitcoin", "btc", "satoshi"},
    "ETH": {"ethereum", "ether", "eth", "vitalik"},
    "SOL": {"solana", "sol"},
    "XRP": {"xrp", "ripple"},
    "DOGE": {"dogecoin", "doge"},
    "ADA": {"cardano", "ada"},
    "AAPL": {"apple", "aapl", "iphone"},
    "NVDA": {"nvidia", "nvda", "gpu", "ai chips"},
    "TSLA": {"tesla", "tsla", "elon musk"},
    "MSFT": {"microsoft", "msft", "azure"},
    "AMZN": {"amazon", "amzn", "aws"},
    "META": {"meta", "facebook", "instagram"},
    "GOOGL": {"alphabet", "google", "googl"},
    "AMD": {"amd", "advanced micro devices"},
    "SPY": {"s&p 500", "spy", "stocks"},
    "QQQ": {"nasdaq", "qqq", "tech stocks"},
    "IWM": {"russell 2000", "iwm", "small caps"},
    "COIN": {"coinbase", "coin stock", "coin shares"},
    "MSTR": {"strategy", "microstrategy", "mstr"},
    "HOOD": {"robinhood", "hood stock", "hood shares"},
}

SEARCH_TERMS_BY_ASSET = {
    "BTC": '"bitcoin" OR BTC crypto',
    "ETH": '"ethereum" OR ether OR ETH crypto',
    "SOL": '"solana" OR SOL crypto',
    "XRP": '"xrp" OR ripple crypto',
    "DOGE": '"dogecoin" OR DOGE crypto',
    "ADA": '"cardano" OR ADA crypto',
    "AAPL": '"Apple" OR AAPL stock',
    "NVDA": '"Nvidia" OR NVDA stock',
    "TSLA": '"Tesla" OR TSLA stock',
    "MSFT": '"Microsoft" OR MSFT stock',
    "AMZN": '"Amazon" OR AMZN stock',
    "META": '"Meta Platforms" OR META stock',
    "GOOGL": '"Alphabet" OR Google OR GOOGL stock',
    "AMD": '"Advanced Micro Devices" OR AMD stock',
    "SPY": '"S&P 500" OR SPY ETF',
    "QQQ": '"Nasdaq 100" OR QQQ ETF',
    "IWM": '"Russell 2000" OR IWM ETF',
    "COIN": '"Coinbase" OR COIN stock',
    "MSTR": '"MicroStrategy" OR MSTR stock',
    "HOOD": '"Robinhood" OR HOOD stock',
}

DEFAULT_NEWS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://www.theblock.co/rss.xml",
    "https://cryptoslate.com/feed/",
    "https://news.bitcoin.com/feed/",
    "https://bitcoinmagazine.com/.rss/full/",
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.marketwatch.com/rss/topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
]

POSITIVE_TERMS = {
    "approval",
    "approved",
    "breakout",
    "bullish",
    "etf inflow",
    "inflow",
    "record high",
    "rally",
    "surge",
    "upgrade",
}

NEGATIVE_TERMS = {
    "ban",
    "bearish",
    "crackdown",
    "crash",
    "default",
    "exploit",
    "hack",
    "investigation",
    "lawsuit",
    "liquidation",
    "outflow",
    "sec sues",
    "sell-off",
}

EXTREME_TERMS = {
    "bankruptcy",
    "exploit",
    "hack",
    "halt",
    "war",
}


def asset_terms(product_id: str) -> set[str]:
    base = product_id.split("-")[0].upper()
    terms = KEYWORDS_BY_ASSET.get(base, {base.lower()})
    if "-" in product_id:
        return terms | {"crypto", "cryptocurrency", "market"}
    return terms | {"stock", "shares", "market", "earnings"}


def expanded_news_feeds(product_id: str, feeds: list[str], *, days: int = 2) -> list[str]:
    base = product_id.split("-")[0].upper()
    fallback = f'"{base}" crypto' if "-" in product_id else f'"{base}" stock'
    query = SEARCH_TERMS_BY_ASSET.get(base, fallback)
    search_feeds = [
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query + f' when:{days}d')}&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query + ' market price trading')}&hl=en-US&gl=US&ceid=US:en",
    ]
    seen: set[str] = set()
    expanded: list[str] = []
    for feed in [*feeds, *search_feeds]:
        if feed not in seen:
            seen.add(feed)
            expanded.append(feed)
    return expanded


def fetch_market_news(
    product_id: str,
    feeds: list[str],
    *,
    max_items: int = 12,
    timeout_seconds: int = 8,
) -> tuple[list[NewsItem], list[str]]:
    terms = asset_terms(product_id)
    items: list[NewsItem] = []
    errors: list[str] = []
    seen_items: set[str] = set()

    for feed in expanded_news_feeds(product_id, feeds):
        try:
            request = Request(
                feed,
                headers={
                    "User-Agent": "TradingBridge/1.0 (+local personal app)",
                    "Accept": "application/rss+xml, application/xml, text/xml",
                },
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                xml = response.read()
            feed_items = _parse_feed(xml, feed)
            for item in feed_items:
                text = f"{item.title} {item.summary}".lower()
                key = _dedupe_key(item)
                if key not in seen_items and any(term in text for term in terms):
                    seen_items.add(key)
                    items.append(item)
        except (ET.ParseError, TimeoutError, URLError, OSError) as exc:
            errors.append(f"{feed}: {exc}")

    items.sort(key=lambda item: item.published, reverse=True)
    return items[:max_items], errors


def headlines_text(items: list[NewsItem]) -> str:
    return "\n".join(f"{item.source}: {item.title}" for item in items)


def infer_news_state(headlines: str) -> tuple[int, NewsBias, EventRisk]:
    text = headlines.lower()
    positive = sum(1 for term in POSITIVE_TERMS if term in text)
    negative = sum(1 for term in NEGATIVE_TERMS if term in text)
    extreme = sum(1 for term in EXTREME_TERMS if term in text)

    raw_score = max(-5, min(5, positive - negative))
    if raw_score >= 2:
        bias: NewsBias = "bullish"
    elif raw_score <= -2:
        bias = "bearish"
    else:
        bias = "neutral"

    if extreme >= 2:
        event_risk: EventRisk = "extreme"
    elif negative or extreme:
        event_risk = "elevated"
    else:
        event_risk = "low"

    return raw_score, bias, event_risk


def _parse_feed(xml: bytes, feed_url: str) -> list[NewsItem]:
    root = ET.fromstring(xml)
    channel_title = _clean(_first_text(root, [".//channel/title", ".//{*}title"])) or feed_url
    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    return [_parse_item(node, channel_title, feed_url) for node in nodes]


def _parse_item(node: ET.Element, source: str, feed_url: str) -> NewsItem:
    title = _clean(_first_text(node, ["title", "{*}title"]))
    item_source = _clean(_first_text(node, ["source", "{*}source"])) or source
    summary = _clean(
        _first_text(
            node,
            ["description", "summary", "{*}summary", "{http://purl.org/rss/1.0/modules/content/}encoded"],
        )
    )
    link = _first_text(node, ["link", "{*}link"]) or feed_url
    atom_link = node.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None and atom_link.attrib.get("href"):
        link = atom_link.attrib["href"]
    published_raw = _first_text(node, ["pubDate", "published", "updated", "{*}published", "{*}updated"])
    published = _parse_date(published_raw)
    return NewsItem(title=title, link=link.strip(), source=item_source, published=published, summary=summary)


def _first_text(node: ET.Element, paths: list[str]) -> str:
    for path in paths:
        found = node.find(path)
        if found is not None and found.text:
            return found.text
    return ""


def _clean(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    replacements = {
        "â": "'",
        "â": "'",
        "â": '"',
        "â": '"',
        "â": "-",
        "â": "-",
        "Â": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def _dedupe_key(item: NewsItem) -> str:
    title = re.sub(r"\s+-\s+[^-]+$", "", item.title.lower())
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    return title or item.link.lower()


def _parse_date(value: str) -> str:
    if not value:
        return datetime.now(UTC).isoformat()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return datetime.now(UTC).isoformat()
