#!/usr/bin/env python3
"""Build a static evening news dashboard from RSS/Atom feeds.

The script deliberately uses only Python's standard library. It calls no LLM,
AI API, analytics service, database, or paid news API.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "pipeline" / "sources.json"
DEFAULT_TEMPLATE = ROOT / "pipeline" / "template.html"
DEFAULT_OUTPUT = ROOT / "dist" / "index.html"
BERLIN = ZoneInfo("Europe/Berlin")

TOPIC_ORDER = ("ai", "local", "de", "eu", "world", "social")
TOPIC_NAMES = {
    "ai": "KI",
    "local": "Lokale KI",
    "de": "Deutschland",
    "eu": "Europa",
    "world": "Weltpolitik",
    "social": "Social Signals",
}
TOPIC_CONTEXT = {
    "ai": "Relevant für den Wettbewerb der KI-Labore, neue Produkte und die Regulierung leistungsfähiger Modelle.",
    "local": "Relevant für offene Modelle, Hardwarebedarf, Datenschutz und KI, die auf dem eigenen Gerät läuft.",
    "de": "Relevant für politische Entscheidungen, Parteien und Debatten in Deutschland.",
    "eu": "Relevant für europäische Regeln, Institutionen und Deutschlands Rolle in der EU.",
    "world": "Relevant für Machtverschiebungen zwischen den USA, China und weiteren internationalen Akteuren.",
    "social": "Community-Signal, keine bestätigte Nachricht. Es zeigt, welche Themen gerade Aufmerksamkeit bekommen.",
}
QUOTAS = {"ai": 6, "local": 3, "de": 5, "eu": 4, "world": 4, "social": 3}
STOPWORDS = {
    "and", "the", "for", "with", "from", "that", "this", "eine", "einer", "eines", "der", "die", "das",
    "den", "dem", "des", "und", "oder", "von", "für", "mit", "auf", "ist", "sind", "im", "in", "zu",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def clean_text(value: str, limit: int = 420) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    shortened = value[: limit - 1].rsplit(" ", 1)[0]
    return (shortened or value[: limit - 1]) + "…"


def parse_date(value: str, fallback: dt.datetime) -> dt.datetime:
    value = (value or "").strip()
    if not value:
        return fallback
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def valid_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def route_topic(source: dict[str, Any], title: str, snippet: str) -> tuple[str, str]:
    """Split the broad Tagesschau feed into useful dashboard sections."""
    topic = source["topic"]
    if source.get("id") != "tagesschau":
        return topic, source["label"]
    text = f"{title} {snippet}".casefold()
    if re.search(r"\bki\b|künstliche intelligenz|openai|anthropic|deepmind|chatgpt", text):
        topic = "ai"
    elif any(word in text for word in ("eu-kommission", "eu-parlament", "europa", "brüssel", "europäische union")):
        topic = "eu"
    elif any(
        word in text
        for word in (
            "usa", "us-", "china", "iran", "israel", "gaza", "syrien", "ukraine", "russland", "nahost",
            "trump", "fed", "notenbank", "nato", "vereinte nationen", "un-", "afrika", "asien",
        )
    ):
        topic = "world"
    return topic, TOPIC_NAMES[topic]


def atom_link(entry: ET.Element) -> str:
    for child in list(entry):
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "")
        rel = child.attrib.get("rel", "alternate")
        if href and rel in {"", "alternate"}:
            return href
    return child_text(entry, "link")


def feed_items(xml_bytes: bytes, source: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    entries = [node for node in root.iter() if local_name(node.tag) in {"item", "entry"}]
    articles: list[dict[str, Any]] = []
    for entry in entries[:30]:
        title = clean_text(child_text(entry, "title"), 220)
        link = atom_link(entry) if local_name(entry.tag) == "entry" else child_text(entry, "link")
        link = valid_url(html.unescape(link))
        if not title or not link:
            continue
        description = child_text(entry, "description", "summary", "content", "encoded")
        snippet = clean_text(description)
        if snippet.casefold().startswith(title.casefold()[: min(50, len(title))]):
            snippet = clean_text(snippet[len(title) :].lstrip(" -–—:"))
        published_raw = child_text(entry, "pubdate", "published", "updated", "date")
        published = parse_date(published_raw, now - dt.timedelta(days=2))
        publisher = clean_text(child_text(entry, "source"), 80) or source["name"]
        topic, label = route_topic(source, title, snippet)
        articles.append(
            {
                "id": hashlib.sha1(f"{title}|{link}".encode("utf-8")).hexdigest()[:12],
                "title": title,
                "url": link,
                "snippet": snippet or "Die Quelle enthält keinen separaten Kurztext. Details stehen im verlinkten Original.",
                "published": published.isoformat(),
                "source": publisher,
                "source_id": source["id"],
                "topic": topic,
                "label": label,
                "kind": source["kind"],
                "priority": int(source.get("priority", 1)),
            }
        )
    return articles


def fetch_source(source: dict[str, Any], now: dt.datetime, timeout: int = 18) -> tuple[list[dict[str, Any]], str]:
    request = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": "LagebildNewsBot/1.0 (+https://github.com/)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(2_500_000)
        return feed_items(payload, source, now), ""
    except Exception as exc:  # One broken source must not break all other sources.
        return [], f"{source['id']}: {type(exc).__name__}: {exc}"


def title_key(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9äöüß]{3,}", title.casefold())
    return {word for word in words if word not in STOPWORDS}


def near_duplicate(first: str, second: str) -> bool:
    left, right = title_key(first), title_key(second)
    if not left or not right:
        return first.casefold() == second.casefold()
    overlap = len(left & right) / min(len(left), len(right))
    return overlap >= 0.72


def score(article: dict[str, Any], now: dt.datetime) -> float:
    published = dt.datetime.fromisoformat(article["published"])
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    recency = max(0.0, 72.0 - age_hours) / 12.0
    official_bonus = 1.5 if article.get("kind") == "official" else 0.0
    title_bonus = min(1.5, len(title_key(article["title"])) / 8)
    return float(article.get("priority", 1)) * 2.0 + recency + official_bonus + title_bonus


def deduplicate(articles: list[dict[str, Any]], now: dt.datetime) -> list[dict[str, Any]]:
    ranked = sorted(articles, key=lambda item: (score(item, now), item["published"]), reverse=True)
    unique: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for article in ranked:
        normalized_url = article["url"].split("#", 1)[0]
        if normalized_url in seen_urls:
            continue
        if any(near_duplicate(article["title"], existing["title"]) for existing in unique):
            continue
        seen_urls.add(normalized_url)
        article["score"] = round(score(article, now), 2)
        unique.append(article)
    return unique


def balanced_selection(articles: list[dict[str, Any]], maximum: int = 24) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for topic in TOPIC_ORDER:
        candidates = [item for item in articles if item["topic"] == topic]
        for item in candidates[: QUOTAS[topic]]:
            selected.append(item)
            used.add(item["id"])
    for item in articles:
        if len(selected) >= maximum:
            break
        if item["id"] not in used:
            selected.append(item)
            used.add(item["id"])
    return sorted(selected[:maximum], key=lambda item: (item["published"], item.get("score", 0)), reverse=True)


def format_age(published: str, now: dt.datetime) -> str:
    moment = dt.datetime.fromisoformat(published)
    hours = max(0, int((now - moment).total_seconds() // 3600))
    if hours < 1:
        return "gerade eben"
    if hours < 24:
        return f"vor {hours} Std."
    days = max(1, hours // 24)
    return f"vor {days} Tag" if days == 1 else f"vor {days} Tagen"


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def story_html(article: dict[str, Any], now: dt.datetime) -> str:
    topic = article["topic"]
    searchable = clean_text(f"{article['title']} {article['snippet']} {article['source']}", 900).casefold()
    return f'''<details class="story topic-{escape(topic)}" data-topic="{escape(topic)}" data-search="{escape(searchable)}">
  <summary>
    <span class="topic-dot" aria-hidden="true"></span>
    <span class="story-copy"><span class="story-meta"><span class="tag">{escape(article['label'])}</span><span>{escape(article['source'])}</span><span>·</span><time datetime="{escape(article['published'])}">{escape(format_age(article['published'], now))}</time></span><span class="story-title">{escape(article['title'])}</span></span>
    <span class="expand" aria-hidden="true">+</span>
  </summary>
  <div class="story-body">
    <p>{escape(article['snippet'])}</p>
    <p class="context"><strong>Kontext:</strong> {escape(TOPIC_CONTEXT[topic])}</p>
    <a class="story-link" href="{escape(article['url'])}" target="_blank" rel="noopener noreferrer">Originalquelle öffnen <span aria-hidden="true">↗</span></a>
  </div>
</details>'''


def render(articles: list[dict[str, Any]], source_count: int, now: dt.datetime, template: str) -> str:
    counts = Counter(item["topic"] for item in articles)
    filters = [{"key": "all", "label": "Alles", "count": len(articles)}]
    filters.extend(
        {"key": topic, "label": TOPIC_NAMES[topic], "count": counts.get(topic, 0)}
        for topic in TOPIC_ORDER
        if counts.get(topic, 0)
    )
    lead = articles[0]
    briefing = "".join(
        f'<li><span class="rail-index">{index:02d}</span><a href="{escape(item["url"])}" target="_blank" rel="noopener noreferrer">{escape(item["title"])}</a></li>'
        for index, item in enumerate(articles[:5], start=1)
    )
    topic_watch = [topic for topic in TOPIC_ORDER if counts.get(topic, 0)][:3]
    watch = "".join(
        f'<li><span class="watch-dot topic-{escape(topic)}"></span><span><strong>{escape(TOPIC_NAMES[topic])}</strong><small>{counts[topic]} neue Signale in dieser Ausgabe</small></span></li>'
        for topic in topic_watch
    )
    berlin_now = now.astimezone(BERLIN)
    replacements = {
        "{{DATE_LONG}}": berlin_now.strftime("%d.%m.%Y"),
        "{{GENERATED_AT}}": berlin_now.strftime("%d.%m.%Y · %H:%M"),
        "{{GENERATED_ISO}}": now.isoformat(),
        "{{STORY_COUNT}}": str(len(articles)),
        "{{SOURCE_COUNT}}": str(source_count),
        "{{LEAD_TITLE}}": escape(lead["title"]),
        "{{LEAD_SUMMARY}}": escape(lead["snippet"]),
        "{{LEAD_URL}}": escape(lead["url"]),
        "{{LEAD_SOURCE}}": escape(lead["source"]),
        "{{ARTICLE_CARDS}}": "\n".join(story_html(item, now) for item in articles),
        "{{BRIEFING_ITEMS}}": briefing,
        "{{WATCH_ITEMS}}": watch,
        "{{FILTERS_JSON}}": json.dumps(filters, ensure_ascii=False).replace("</", "<\\/"),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if re.search(r"{{[A-Z0-9_]+}}", template):
        raise ValueError("Unreplaced template marker found")
    return template


def load_fixture(path: Path, now: dt.datetime) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    articles: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        article = dict(item)
        article.setdefault("id", f"fixture-{index}")
        article.setdefault("kind", "news")
        article.setdefault("priority", 3)
        article.setdefault("published", (now - dt.timedelta(hours=index + 1)).isoformat())
        articles.append(article)
    return articles


def quality_gate(articles: list[dict[str, Any]], minimum: int) -> None:
    core_topics = {item["topic"] for item in articles if item["topic"] in {"ai", "de", "eu", "world"}}
    if len(articles) < minimum:
        raise RuntimeError(f"Quality gate: only {len(articles)} articles, need at least {minimum}")
    if len(core_topics) < 3:
        raise RuntimeError(f"Quality gate: only {len(core_topics)} core topics represented, need at least 3")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fixture", type=Path, help="Use local JSON articles instead of the network")
    parser.add_argument("--minimum", type=int, default=8)
    parser.add_argument("--now", help="ISO timestamp for deterministic tests/previews")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)

    errors: list[str] = []
    if args.fixture:
        raw_articles = load_fixture(args.fixture, now)
        source_count = len({item["source"] for item in raw_articles})
    else:
        sources = json.loads(args.sources.read_text(encoding="utf-8"))
        raw_articles = []
        successful_sources = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(sources))) as executor:
            futures = [executor.submit(fetch_source, source, now) for source in sources]
            for future in concurrent.futures.as_completed(futures):
                items, error = future.result()
                raw_articles.extend(items)
                successful_sources += int(bool(items))
                if error:
                    errors.append(error)
        source_count = successful_sources

    selected = balanced_selection(deduplicate(raw_articles, now))
    quality_gate(selected, args.minimum)
    template = args.template.read_text(encoding="utf-8")
    output = render(selected, source_count, now, template)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")

    print(f"Built {args.output} with {len(selected)} articles from {source_count} sources")
    for error in sorted(errors):
        print(f"WARN {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
