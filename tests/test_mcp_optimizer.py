"""MCP 토큰 최적화 유틸리티 테스트 (네트워크·API 키 없이 실행).

    python -m unittest discover -s tests -v
    python -m unittest tests.test_mcp_optimizer -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.mcp_token_optimizer import (  # noqa: E402
    ToolRouter,
    ToolSpec,
    build_tool_search_tool,
    compact_json,
    estimate_json_tokens,
    estimate_savings,
    estimate_tokens,
    paginate,
    payload_report,
    project_fields,
    prune_schema,
    prune_tool_definition,
    sample_catalog,
    strip_empty,
    summarize_records,
    to_markdown_table,
    to_tsv,
    truncate_text,
)


def make_tool(name: str, description: str, server: str = "demo", **kwargs) -> ToolSpec:
    return ToolSpec(name=name, description=description, server=server, **kwargs)


class TokenEstimateTest(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_ascii_four_chars_per_token(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 2)

    def test_korean_is_one_per_char(self):
        # 한글 6자 → 6토큰 근사(영문 대비 훨씬 비싸다)
        self.assertEqual(estimate_tokens("안녕하세요반"), 6)

    def test_compact_json_is_shorter(self):
        payload = {"a": 1, "b": [1, 2, 3], "c": "값"}
        pretty = json.dumps(payload, ensure_ascii=False)
        self.assertLess(len(compact_json(payload)), len(pretty))
        self.assertLess(estimate_json_tokens(payload), estimate_tokens(pretty))

    def test_non_negative_on_repeated_text(self):
        text = "mcp token " * 50
        self.assertGreater(estimate_tokens(text), 50)


class CatalogTest(unittest.TestCase):
    def test_catalog_has_one_hundred_unique_tools(self):
        catalog = sample_catalog()
        self.assertEqual(len(catalog), 100)
        names = [t.qualified_name for t in catalog]
        self.assertEqual(len(set(names)), 100)

    def test_catalog_is_deterministic(self):
        a = [t.qualified_name for t in sample_catalog()]
        b = [t.qualified_name for t in sample_catalog()]
        self.assertEqual(a, b)

    def test_baseline_is_large(self):
        router = ToolRouter(sample_catalog())
        baseline = router.baseline_tokens()
        self.assertGreater(baseline, 30_000)
        self.assertLess(baseline, 60_000)

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):
            ToolRouter([make_tool("x", "a"), make_tool("x", "b")])

    def test_empty_catalog_rejected(self):
        with self.assertRaises(ValueError):
            ToolRouter([])


class RouterSelectionTest(unittest.TestCase):
    def setUp(self):
        self.router = ToolRouter(sample_catalog())

    def test_korean_query_routes_to_postgres(self):
        picked = self.router.select("게시판 DB에서 가입자 수를 조회해줘", k=2, min_relative_score=0.55)
        self.assertTrue(picked)
        self.assertEqual(picked[0].qualified_name, "postgres__query")

    def test_cross_server_query_picks_two_tools(self):
        picked = self.router.select(
            "열린 버그 이슈 목록을 GitHub에서 뽑아서 Slack으로 알려줘", k=2, min_relative_score=0.55
        )
        names = [t.qualified_name for t in picked]
        self.assertIn("github__list_issues", names)
        self.assertIn("slack__post_message", names)

    def test_k_limits_selection(self):
        for k in (1, 2, 3):
            picked = self.router.select("issue database slack browser files", k=k)
            self.assertLessEqual(len(picked), k)

    def test_token_budget_is_respected(self):
        picked = self.router.select("issue database slack browser files notion aws", k=10, max_tokens=1200)
        self.assertGreaterEqual(len(picked), 1)
        self.assertLessEqual(sum(t.token_cost() for t in picked), 1200)

    def test_detail_name_is_cheaper(self):
        full = self.router.select("이슈 목록", k=3)
        names_only = self.router.select("이슈 목록", k=3, detail="name")
        cost_full = sum(t.token_cost("full") for t in full)
        cost_name = sum(t.token_cost("name") for t in names_only)
        self.assertLess(cost_name, cost_full / 10)

    def test_selection_is_order_independent(self):
        """카탈로그 순서가 흔들려도 같은 결과가 나와야 프롬프트 캐시가 유지된다."""
        query = "Sentry 에러 스택트레이스를 확인해줘"
        first = [t.qualified_name for t in self.router.select(query, k=3)]
        shuffled = ToolRouter(list(reversed(sample_catalog())))
        second = [t.qualified_name for t in shuffled.select(query, k=3)]
        self.assertEqual(sorted(first), sorted(second))
        self.assertEqual(first, second)

    def test_repeated_calls_are_identical(self):
        query = "이번 달 AWS 비용 리포트"
        self.assertEqual(
            [t.qualified_name for t in self.router.select(query, k=3)],
            [t.qualified_name for t in self.router.select(query, k=3)],
        )

    def test_always_includes_pinned_tool(self):
        picked = self.router.select("비용", k=2, always=["filesystem__read_file"])
        self.assertEqual(picked[0].qualified_name, "filesystem__read_file")

    def test_empty_query_selects_nothing_by_default(self):
        self.assertEqual(self.router.select("", k=3), [])

    def test_relative_floor_drops_weak_candidates(self):
        query = "Notion 데이터베이스에서 진행 중인 작업만 찾아줘"
        loose = self.router.select(query, k=5, min_relative_score=0.0)
        strict = self.router.select(query, k=5, min_relative_score=0.8)
        self.assertGreater(len(loose), len(strict))
        self.assertEqual(strict[0].qualified_name, "notion__query_database")

    def test_route_reports_savings(self):
        routed = self.router.route("Sentry 에러를 확인해줘", k=2)
        self.assertGreater(routed.savings["saved_pct"], 90.0)
        self.assertEqual(routed.baseline_tokens, self.router.baseline_tokens())
        self.assertEqual(routed.routed_tokens, estimate_json_tokens(routed.definitions))
        self.assertEqual(len(routed.definitions), len(routed.selected))


class EmbeddingRouterTest(unittest.TestCase):
    @staticmethod
    def fake_embed(text: str):
        lowered = text.lower()
        money = any(w in lowered for w in ("cost", "billing", "spend", "pay", "비용", "청구"))
        database = any(w in lowered for w in ("sql", "database", "query", "db", "조회"))
        return [1.0 if money else 0.0, 1.0 if database else 0.0, 0.1]

    def test_semantic_only_routing_without_lexical_overlap(self):
        router = ToolRouter(sample_catalog(), embed=self.fake_embed, alpha=1.0)
        picked = router.select("how much did we pay last month", k=1)
        self.assertEqual(picked[0].qualified_name, "aws__cost_report")

    def test_hybrid_router_still_answers_keyword_query(self):
        router = ToolRouter(sample_catalog(), embed=self.fake_embed, alpha=0.5)
        picked = router.select("postgres sql 조회", k=2)
        self.assertEqual(picked[0].server, "postgres")


class SchemaPruningTest(unittest.TestCase):
    def schema(self):
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "create_issue",
            "properties": {
                "title": {
                    "title": "Title",
                    "type": "string",
                    "description": "The issue title. " * 20,
                    "examples": ["bug: login"],
                },
                "labels": {
                    "title": "Labels",
                    "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                    "default": None,
                },
                "priority": {"type": "integer", "enum": [1, 2, 3], "minimum": 1, "maximum": 3},
            },
            "required": ["title"],
        }

    def test_generator_artifacts_removed(self):
        pruned = prune_schema(self.schema())
        text = compact_json(pruned)
        self.assertNotIn("$schema", text)
        self.assertNotIn("title", pruned)
        for prop in pruned["properties"].values():
            self.assertNotIn("title", prop)
            self.assertNotIn("examples", prop)
            self.assertNotIn("default", prop)

    def test_nullable_union_collapsed(self):
        pruned = prune_schema(self.schema())
        labels = pruned["properties"]["labels"]
        self.assertEqual(labels["type"], "array")
        self.assertNotIn("anyOf", labels)

    def test_judgement_fields_kept(self):
        pruned = prune_schema(self.schema())
        priority = pruned["properties"]["priority"]
        self.assertEqual(priority["enum"], [1, 2, 3])
        self.assertEqual(priority["minimum"], 1)
        self.assertEqual(pruned["required"], ["title"])

    def test_long_description_truncated(self):
        pruned = prune_schema(self.schema(), max_description_chars=40)
        desc = pruned["properties"]["title"]["description"]
        self.assertLessEqual(len(desc), 40)
        self.assertTrue(desc.endswith("…"))

    def test_pruned_tool_definition_saves_tokens(self):
        raw = {
            "name": "create_issue",
            "description": "Create an issue. " * 30,
            "input_schema": self.schema(),
        }
        pruned = prune_tool_definition(raw, max_description_chars=120)
        before = estimate_json_tokens(raw)
        after = estimate_json_tokens(pruned)
        self.assertLess(after, before * 0.6)
        self.assertEqual(pruned["name"], "create_issue")

    def test_max_properties_keeps_required(self):
        pruned = prune_tool_definition(
            {"name": "t", "description": "d", "input_schema": self.schema()},
            max_properties=1,
        )
        props = pruned["input_schema"]["properties"]
        self.assertEqual(list(props), ["title"])

    def test_camel_case_schema_key_supported(self):
        pruned = prune_tool_definition(
            {"name": "t", "description": "d", "inputSchema": self.schema()}
        )
        self.assertIn("inputSchema", pruned)
        self.assertNotIn("$schema", compact_json(pruned))


class PayloadTest(unittest.TestCase):
    def rows(self, n: int = 50):
        return [
            {
                "id": i,
                "title": f"Login fails on Android build {i}",
                "state": "open" if i % 2 else "closed",
                "labels": ["bug"],
                "assignee": None,
                "body": "재현 절차 " + "x" * 30,
            }
            for i in range(n)
        ]

    def test_markdown_table_much_smaller_than_json(self):
        rows = self.rows()
        table = to_markdown_table(rows, columns=["id", "title", "state"])
        before = estimate_json_tokens(rows)
        after = estimate_tokens(table)
        self.assertLess(after, before * 0.5)

    def test_tsv_even_smaller_than_table(self):
        rows = self.rows(20)
        self.assertLess(
            estimate_tokens(to_tsv(rows, columns=["id", "title", "state"])),
            estimate_tokens(to_markdown_table(rows, columns=["id", "title", "state"])),
        )

    def test_table_escapes_pipes_and_newlines(self):
        table = to_markdown_table([{"a": "x|y", "b": "line\nbreak"}])
        self.assertIn("x\\|y", table)
        self.assertNotIn("\nbreak", table)

    def test_table_handles_empty(self):
        self.assertEqual(to_markdown_table([]), "(no rows)")

    def test_summary_first_has_total_and_hint(self):
        text = summarize_records(self.rows(300), columns=["id", "state"], preview=5, label="issues")
        self.assertIn("total issues: 300", text)
        self.assertIn("offset=5", text)
        data_rows = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line]
        self.assertEqual(len(data_rows), 6)  # 헤더 1 + 미리보기 5

    def test_summary_without_truncation_has_no_hint(self):
        text = summarize_records(self.rows(3), preview=5, hint=False)
        self.assertIn("total rows: 3", text)
        self.assertNotIn("offset=", text)

    def test_summary_saves_tokens(self):
        rows = self.rows(200)
        text = summarize_records(rows, columns=["id", "title"], preview=5, label="issues")
        report = payload_report(rows, text)
        self.assertGreater(report["saved_pct"], 95.0)
        self.assertEqual(report["before_tokens"], report["before_tokens"])

    def test_paginate_middle_page(self):
        page = paginate(self.rows(50), offset=10, limit=5)
        self.assertEqual(page["total"], 50)
        self.assertEqual(page["returned"], 5)
        self.assertEqual(page["next_offset"], 15)
        self.assertEqual(page["items"][0]["id"], 10)

    def test_paginate_last_page(self):
        page = paginate(self.rows(12), offset=10, limit=5)
        self.assertEqual(page["returned"], 2)
        self.assertIsNone(page["next_offset"])

    def test_paginate_rejects_bad_args(self):
        with self.assertRaises(ValueError):
            paginate(self.rows(3), offset=-1)
        with self.assertRaises(ValueError):
            paginate(self.rows(3), limit=0)

    def test_strip_empty_removes_nulls_deeply(self):
        cleaned = strip_empty({"a": None, "b": "", "c": [], "d": {"e": None, "f": 1}, "g": [1, None]})
        self.assertEqual(cleaned, {"d": {"f": 1}, "g": [1]})

    def test_project_fields(self):
        rows = self.rows(3)
        projected = project_fields(rows, ["id", "missing"])
        self.assertEqual(projected, [{"id": 0}, {"id": 1}, {"id": 2}])

    def test_truncate_keeps_head_and_tail(self):
        text = "HEAD " + ("middle " * 2000) + "TAIL"
        cut = truncate_text(text, max_tokens=100, keep_tail_ratio=0.2)
        self.assertLess(estimate_tokens(cut), 160)
        self.assertTrue(cut.startswith("HEAD"))
        self.assertTrue(cut.endswith("TAIL"))
        self.assertIn("truncated", cut)

    def test_truncate_returns_short_text_unchanged(self):
        self.assertEqual(truncate_text("short", 100), "short")

    def test_truncate_rejects_zero_budget(self):
        with self.assertRaises(ValueError):
            truncate_text("abc", 0)


class SavingsTest(unittest.TestCase):
    def test_savings_percent(self):
        result = estimate_savings(1000, 250)
        self.assertEqual(result["saved_tokens"], 750)
        self.assertEqual(result["saved_pct"], 75.0)

    def test_zero_baseline_is_safe(self):
        self.assertEqual(estimate_savings(0, 0)["saved_pct"], 0.0)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            estimate_savings(-1, 0)

    def test_increase_reports_negative_pct(self):
        self.assertEqual(estimate_savings(100, 150)["saved_pct"], -50.0)


class MetaToolTest(unittest.TestCase):
    def test_search_tool_shape(self):
        tool = build_tool_search_tool()
        self.assertEqual(tool["name"], "search_tools")
        props = tool["input_schema"]["properties"]
        self.assertIn("detail", props)
        self.assertIn("full", props["detail"]["enum"])
        self.assertEqual(tool["input_schema"]["required"], ["query"])

    def test_search_tool_is_cheap(self):
        # 전체 카탈로그(3만 토큰대) 대비 200토큰 수준
        self.assertLess(estimate_json_tokens(build_tool_search_tool()), 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
