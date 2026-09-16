import datetime as dt
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import update_dashboard as dashboard


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 16, 16, 30, tzinfo=dt.timezone.utc)

    def test_parses_rss_and_atom(self):
        source = {
            "id": "test",
            "name": "Testquelle",
            "topic": "ai",
            "label": "KI",
            "kind": "news",
            "priority": 3,
        }
        rss = b"""<?xml version='1.0'?><rss><channel><item><title>Ein neuer Test</title><link>https://example.com/a</link><description><![CDATA[<p>Kurzer Text.</p>]]></description><pubDate>Wed, 16 Sep 2026 15:00:00 GMT</pubDate></item></channel></rss>"""
        atom = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Noch ein Test</title><link href='https://example.com/b'/><summary>Atom-Text.</summary><updated>2026-09-16T14:00:00Z</updated></entry></feed>"""
        self.assertEqual(dashboard.feed_items(rss, source, self.now)[0]["snippet"], "Kurzer Text.")
        self.assertEqual(dashboard.feed_items(atom, source, self.now)[0]["url"], "https://example.com/b")

    def test_deduplicates_similar_titles(self):
        base = {
            "url": "https://example.com/1",
            "snippet": "Text",
            "published": self.now.isoformat(),
            "source": "A",
            "source_id": "a",
            "topic": "ai",
            "label": "KI",
            "kind": "news",
            "priority": 3,
        }
        first = {**base, "id": "1", "title": "OpenAI zeigt ein neues Modell für Entwickler"}
        second = {**base, "id": "2", "url": "https://example.com/2", "title": "OpenAI zeigt neues Modell für die Entwickler"}
        self.assertEqual(len(dashboard.deduplicate([first, second], self.now)), 1)

    def test_routes_international_tagesschau_story(self):
        source = {"id": "tagesschau", "topic": "de", "label": "Deutschland"}
        topic, label = dashboard.route_topic(source, "US-Notenbank erhöht den Leitzins", "Die Fed reagiert")
        self.assertEqual((topic, label), ("world", "Weltpolitik"))

    def test_fixture_build_is_complete_and_safe(self):
        fixture = ROOT / "pipeline" / "fixtures" / "articles.json"
        output = ROOT / "dist" / "_test-index.html"
        try:
            result = dashboard.main(
                [
                    "--fixture",
                    str(fixture),
                    "--output",
                    str(output),
                    "--now",
                    self.now.isoformat(),
                    "--minimum",
                    "8",
                ]
            )
            page = output.read_text(encoding="utf-8")
        finally:
            output.unlink(missing_ok=True)
        self.assertEqual(result, 0)
        self.assertIn("OpenAI veröffentlicht", page)
        self.assertIn("data-topic=\"social\"", page)
        self.assertNotIn("{{ARTICLE_CARDS}}", page)
        self.assertNotIn("OpenAI API", page)

    def test_quality_gate_rejects_thin_output(self):
        with self.assertRaises(RuntimeError):
            dashboard.quality_gate([{"topic": "ai"}], minimum=8)


if __name__ == "__main__":
    unittest.main()
