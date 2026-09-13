import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.sdk_stubs import install_stubs

install_stubs()

from components.observability.telemetry import LangRAGTelemetry
from components.pages.observability import LangRAGObservabilityPage
from langbot_plugin.api.definition.components.page import PageRequest


class TelemetryTests(unittest.TestCase):
    def test_ring_buffer_and_query_redaction(self):
        store = LangRAGTelemetry(max_events=2, persist_path=None)

        store.record_retrieval(
            query="full user query should not be stored",
            collection_id="kb1",
            status="completed",
            duration_ms=4.2,
            index_type="chunk",
            search_type="vector",
            top_k=3,
            raw_count=5,
            result_count=2,
            reference_count=1,
            stage_durations_ms={"query_embedding": 1.2, "vector_search": 2.4},
            retrieval_settings={"top_k": 3, "search_type": "vector"},
        )
        store.record_ingest(
            document_id="doc1",
            filename="a.txt",
            collection_id="kb1",
            status="completed",
            duration_ms=1.0,
            chunks_created=1,
        )
        store.record_ingest(
            document_id="doc2",
            filename="b.txt",
            collection_id="kb1",
            status="failed",
            duration_ms=2.0,
            error="boom",
        )
        store.record_ingest(
            document_id="doc3",
            filename="c.txt",
            collection_id="kb1",
            status="completed",
            duration_ms=3.0,
            chunks_created=2,
        )

        snapshot = store.snapshot()

        self.assertEqual(len(snapshot["recent"]["ingest"]), 2)
        self.assertEqual(snapshot["counters"]["ingest.total"], 3)
        self.assertEqual(snapshot["counters"]["retrieval.total"], 1)
        self.assertNotIn("full user query should not be stored", repr(snapshot))
        retrieval = snapshot["recent"]["retrieval"][0]
        self.assertEqual(retrieval["query_length"], 36)
        self.assertIsNotNone(retrieval["query_hash"])
        self.assertIn("1m", snapshot["windows"])
        self.assertEqual(snapshot["latency"]["retrieval"]["p95"], 4.2)
        self.assertIn("query_embedding", snapshot["latency"]["retrieval"]["stages_ms"])
        self.assertEqual(snapshot["quality"]["retrieval"]["zero_result_rate"], 0)

    def test_windows_percentiles_alerts_and_prometheus(self):
        store = LangRAGTelemetry(max_events=10, persist_path=None)

        for i in range(5):
            store.record_retrieval(
                query=f"q{i}",
                collection_id="kb1",
                status="completed",
                duration_ms=10 + i,
                top_k=3,
                raw_count=0,
                result_count=0,
                retrieval_settings={"top_k": 3},
            )

        snapshot = store.snapshot()

        self.assertEqual(snapshot["windows"]["5m"]["retrieval"]["events"], 5)
        self.assertEqual(snapshot["windows"]["5m"]["retrieval"]["zero_result_rate"], 1)
        self.assertTrue(
            any(alert["code"] == "retrieval_zero_results" for alert in snapshot["alerts"])
        )
        self.assertIn("p99", snapshot["latency"]["retrieval"])
        prometheus = store.prometheus()
        self.assertIn('langrag_retrieval_zero_result_rate{instance="', prometheus)
        self.assertIn("} 1.0", prometheus)
        self.assertIn("langrag_operation_events_total", prometheus)
        self.assertIn("langrag_window_error_rate", prometheus)
        self.assertIn("langrag_persistence_enabled", prometheus)

    def test_persistence_round_trip_uses_jsonl_without_query_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            store = LangRAGTelemetry(max_events=10, persist_path=path)
            store.record_retrieval(
                query="sensitive query text",
                collection_id="kb1",
                status="completed",
                duration_ms=12,
                top_k=3,
                result_count=1,
            )

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("sensitive query text", raw)
            self.assertEqual(len([line for line in raw.splitlines() if line]), 1)
            self.assertIsInstance(json.loads(raw.splitlines()[0]), dict)

            reloaded = LangRAGTelemetry(max_events=10, persist_path=path)
            snapshot = reloaded.snapshot()
            self.assertEqual(snapshot["persistence"]["loaded_events"], 1)
            self.assertEqual(snapshot["counters"]["retrieval.total"], 1)


class ObservabilityPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_and_clear_endpoints(self):
        from components.observability import telemetry

        telemetry.clear()
        telemetry.record_delete(
            collection_id="kb1",
            document_id="doc1",
            status="completed",
            duration_ms=5.0,
            deleted=True,
            vectors_deleted=2,
        )

        page = LangRAGObservabilityPage()
        response = await page.handle_api(
            PageRequest(endpoint="/snapshot", method="GET")
        )

        self.assertIsNone(response.error)
        self.assertEqual(response.data["counters"]["delete.total"], 1)

        response = await page.handle_api(PageRequest(endpoint="/metrics", method="GET"))

        self.assertIsNone(response.error)
        self.assertEqual(response.data["content_type"], "text/plain; version=0.0.4")
        self.assertIn("langrag_operations_total", response.data["body"])

        response = await page.handle_api(PageRequest(endpoint="/clear", method="POST"))

        self.assertIsNone(response.error)
        self.assertEqual(response.data["counters"], {})

    async def test_unknown_endpoint_fails(self):
        response = await LangRAGObservabilityPage().handle_api(
            PageRequest(endpoint="/missing", method="GET")
        )

        self.assertIn("Unknown endpoint", response.error)

    def test_i18n_assets_exist(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ("en_US.json", "zh_Hans.json"):
            path = root / "components" / "pages" / "i18n" / filename
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("title", data)
            self.assertIn("sections.window", data)

    def test_sensitive_query_log_patterns_are_not_present(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "components/knowledge_engine/langrag.py",
            "components/knowledge_engine/query_rewrite.py",
            "components/knowledge_engine/rerank.py",
        ):
            source = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn("query={query!r}", source)
            self.assertNotIn("query: {query!r}", source)
            self.assertNotIn("LLM response: {raw!r}", source)
            self.assertNotIn("Hypothetical document:\\n{hypothetical_doc}", source)


if __name__ == "__main__":
    unittest.main()
