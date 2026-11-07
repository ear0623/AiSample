"""오픈월드 헬퍼 계산기 테스트 (엔진·네트워크 없이 실행).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import open_world_helper as ow  # noqa: E402


class CellsInRadiusTest(unittest.TestCase):
    def test_circle_excludes_corners(self) -> None:
        # 256 m 셀, 768 m 반경: 7x7=49가 아니라 모서리가 빠진 45.
        self.assertEqual(ow.cells_in_radius(256, 768), 45)

    def test_tight_radius_is_single_cell(self) -> None:
        self.assertEqual(ow.cells_in_radius(256, 1), 1)
        # 반경이 셀 반폭과 같으면 네 이웃 셀 경계에 닿는다 -> 5.
        self.assertEqual(ow.cells_in_radius(256, 128), 5)

    def test_exact_cell_multiple(self) -> None:
        # 반경 2셀(512 m): 5x5에서 네 모서리만 빠진 21.
        self.assertEqual(ow.cells_in_radius(256, 512), 21)

    def test_half_cell_offset_radius(self) -> None:
        # 반경 1.5셀(384 m)이면 축 방향 2셀까지 걸치고 대각 2,1은 밖이다.
        self.assertEqual(ow.cells_in_radius(256, 384), 13)

    def test_rejects_non_positive(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.cells_in_radius(0, 100)
        with self.assertRaises(ow.PlanError):
            ow.cells_in_radius(100, -1)


class NextPowerOfTwoTest(unittest.TestCase):
    def test_values(self) -> None:
        self.assertEqual(ow.next_power_of_two(1), 1)
        self.assertEqual(ow.next_power_of_two(17), 32)
        self.assertEqual(ow.next_power_of_two(256), 256)
        self.assertEqual(ow.next_power_of_two(257), 512)


class GridPlanTest(unittest.TestCase):
    def test_default_open_world_grid(self) -> None:
        plan = ow.calculate_grid(8000, 256, 768)
        self.assertEqual(plan.cells_per_axis, 32)
        self.assertEqual(plan.total_cells, 1024)
        self.assertEqual(plan.loaded_cells_per_axis, 7)
        self.assertEqual(plan.max_loaded_cells, 45)
        self.assertAlmostEqual(plan.loaded_fraction, 45 / 1024)

    def test_non_multiple_world_rounds_up(self) -> None:
        plan = ow.calculate_grid(8100, 256, 768)
        self.assertEqual(plan.cells_per_axis, 32)  # 31.64 -> 32
        plan = ow.calculate_grid(8200, 256, 768)
        self.assertEqual(plan.cells_per_axis, 33)

    def test_small_world_loaded_fraction_capped_by_grid(self) -> None:
        plan = ow.calculate_grid(512, 256, 1024)
        self.assertEqual(plan.total_cells, 4)
        self.assertGreater(plan.max_loaded_cells, plan.total_cells)
        # 이론값은 그리드보다 클 수 있으므로 비율이 1을 넘는다 -> 문서에서 주의.
        self.assertGreater(plan.loaded_fraction, 1.0)

    def test_invalid_inputs(self) -> None:
        for kwargs in ({"world_size_m": 0, "cell_size_m": 256, "loading_range_m": 768},
                       {"world_size_m": 100, "cell_size_m": -1, "loading_range_m": 768},
                       {"world_size_m": 100, "cell_size_m": 256, "loading_range_m": float("nan")}):
            with self.assertRaises(ow.PlanError):
                ow.calculate_grid(**kwargs)


class StreamingEstimateTest(unittest.TestCase):
    def test_walk_speed(self) -> None:
        plan = ow.calculate_grid(8000, 256, 768)
        est = ow.estimate_streaming(plan, 30 * 1024 * 1024, speed_mps=6.0)
        self.assertAlmostEqual(est.seconds_per_cell, 256 / 6)
        self.assertAlmostEqual(est.load_window_s, (768 - 128) / 6)
        self.assertAlmostEqual(est.required_mb_per_s, 30 / est.load_window_s, places=6)
        self.assertAlmostEqual(est.resident_mb, 45 * 30, places=6)

    def test_zero_window_when_range_smaller_than_half_cell(self) -> None:
        plan = ow.calculate_grid(8000, 256, 100)
        est = ow.estimate_streaming(plan, 1024)
        self.assertEqual(est.load_window_s, 0.0)
        self.assertEqual(est.required_mb_per_s, float("inf"))

    def test_faster_player_needs_more_bandwidth(self) -> None:
        plan = ow.calculate_grid(8000, 256, 768)
        slow = ow.estimate_streaming(plan, 10_000_000, speed_mps=2)
        fast = ow.estimate_streaming(plan, 10_000_000, speed_mps=20)
        self.assertGreater(fast.required_mb_per_s, slow.required_mb_per_s)


class LandscapePlanTest(unittest.TestCase):
    def test_four_km_at_one_metre(self) -> None:
        plan = ow.plan_landscape(4000, 1.0)
        self.assertEqual(plan.size_vertices, 4033)
        self.assertEqual(plan.tiles_across, 1)
        self.assertEqual(plan.quads_per_section, 63)
        self.assertEqual(plan.component_quads, 126)
        self.assertEqual(plan.components_per_axis, 32)
        self.assertEqual(plan.total_components, 1024)
        self.assertEqual(plan.draw_calls, 4096)
        self.assertAlmostEqual(plan.size_m, 4000.0)
        self.assertAlmostEqual(plan.vertex_spacing_m, 4000 / 4032)
        self.assertAlmostEqual(plan.z_scale, 100.0)
        self.assertAlmostEqual(plan.height_range_m, 512.0)
        self.assertFalse(plan.warnings)

    def test_height_precision_matches_houdini_documented_example(self) -> None:
        # Houdini 문서: 4 km 높이 범위, 3/4 사용 시 8.13 cm, 전 범위 사용 시 6.10 cm.
        plan = ow.plan_landscape(4000, 1.0, height_range_m=4000, full_resolution=False)
        self.assertAlmostEqual(plan.height_precision_cm, 8.14, places=1)
        plan = ow.plan_landscape(4000, 1.0, height_range_m=4000, full_resolution=True)
        self.assertAlmostEqual(plan.height_precision_cm, 6.10, places=1)
        self.assertAlmostEqual(plan.z_scale, 4000 * 100 / 512)

    def test_eight_km_uses_largest_size_and_tiles(self) -> None:
        plan = ow.plan_landscape(8200, 1.0)
        self.assertEqual(plan.tiles_across, 2)
        self.assertEqual(plan.size_vertices, 8129)
        self.assertEqual(plan.quads_per_section, 127)
        self.assertEqual(plan.total_components, 1024)
        self.assertTrue(any("tiles" in w for w in plan.warnings))

    def test_use_full_resolution_flag(self) -> None:
        small = ow.plan_landscape(4000, 1.0)
        full = ow.plan_landscape(4000, 1.0, full_resolution=True)
        self.assertGreater(small.height_precision_cm, full.height_precision_cm)

    def test_custom_sections_trigger_component_warning(self) -> None:
        plan = ow.plan_landscape(4000, 1.0, quads_per_section=7)
        self.assertGreater(plan.total_components, ow.LANDSCAPE_MAX_COMPONENTS)
        self.assertTrue(any("components" in w for w in plan.warnings))

    def test_invalid_section_count(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.plan_landscape(1000, 1.0, sections_per_component=2)

    def test_invalid_quads(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.plan_landscape(1000, 1.0, quads_per_section=64)

    def test_invalid_spacing(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.plan_landscape(1000, 0)

    def test_invalid_height_range(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.plan_landscape(1000, 1.0, height_range_m=-5)

    def test_pick_size(self) -> None:
        self.assertEqual(ow.pick_landscape_size(120), 127)
        self.assertEqual(ow.pick_landscape_size(127), 127)
        self.assertEqual(ow.pick_landscape_size(128), 253)
        with self.assertRaises(ow.PlanError):
            ow.pick_landscape_size(9000)

    def test_heightmap_memory(self) -> None:
        plan = ow.plan_landscape(2016, 1.0)
        self.assertEqual(plan.size_vertices, 2017)
        self.assertAlmostEqual(plan.heightmap_mb, 2017 * 2017 * 2 / 1e6, places=4)


class RvtBudgetTest(unittest.TestCase):
    def test_four_k_rvt_with_256_tiles(self) -> None:
        budget = ow.calculate_rvt(8129, 0.5, tile_size=256, layout="base_color_normal")
        self.assertEqual(budget.resolution, 4096)
        self.assertEqual(budget.tiles_per_axis, 16)
        self.assertEqual(budget.tiles_mip0, 256)
        self.assertAlmostEqual(budget.effective_texels_per_m, 4096 / 8129)
        self.assertAlmostEqual(budget.bytes_per_texel, 1.5)
        self.assertAlmostEqual(budget.mip0_mb, 4096 * 4096 * 1.5 / 1024**2)
        self.assertAlmostEqual(budget.all_mips_mb, budget.mip0_mb * 4 / 3)

    def test_clamps_at_max_resolution(self) -> None:
        budget = ow.calculate_rvt(20000, 1.0, max_tiles_per_axis=64, tile_size=256)
        self.assertEqual(budget.resolution, 16384)
        self.assertTrue(any("clamped" in w for w in budget.warnings))
        self.assertGreater(budget.requested_texels_per_m, budget.effective_texels_per_m)

    def test_uncompressed_is_much_larger(self) -> None:
        comp = ow.calculate_rvt(4000, 1.0, layout="base_color_normal_roughness_specular")
        raw = ow.calculate_rvt(4000, 1.0, layout="base_color_normal_roughness_specular", compressed=False)
        self.assertAlmostEqual(comp.bytes_per_texel, 1.5)
        self.assertAlmostEqual(raw.bytes_per_texel, 12.0)
        self.assertGreater(raw.mip0_mb, comp.mip0_mb * 4)
        self.assertTrue(any("uncompressed" in w for w in raw.warnings))

    def test_layout_byte_table(self) -> None:
        base = ow.calculate_rvt(1000, 1.0, layout="base_color")
        self.assertAlmostEqual(base.bytes_per_texel, 0.5)
        mask = ow.calculate_rvt(1000, 1.0, layout="base_color_normal_roughness_specular_mask")
        self.assertAlmostEqual(mask.bytes_per_texel, 2.5)

    def test_coarse_density_warns(self) -> None:
        budget = ow.calculate_rvt(100_000, 0.001)
        self.assertTrue(any("coarse" in w for w in budget.warnings))

    def test_pool_estimate_scales_with_coverage(self) -> None:
        low = ow.calculate_rvt(4000, 1.0, pool_coverage=0.2)
        high = ow.calculate_rvt(4000, 1.0, pool_coverage=0.8)
        self.assertAlmostEqual(high.pool_estimate_mb, low.pool_estimate_mb * 4)

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.calculate_rvt(1000, 1.0, tile_size=100)
        with self.assertRaises(ow.PlanError):
            ow.calculate_rvt(1000, 1.0, max_tiles_per_axis=48)  # 2의 거듭제곱 아님
        with self.assertRaises(ow.PlanError):
            ow.calculate_rvt(1000, 1.0, max_tiles_per_axis=128)  # 16384 타일 > 4096 상한
        with self.assertRaises(ow.PlanError):
            ow.calculate_rvt(1000, 1.0, layout="unknown")
        with self.assertRaises(ow.PlanError):
            ow.calculate_rvt(1000, 1.0, pool_coverage=0)


class HlodPlanTest(unittest.TestCase):
    def test_two_layer_plan(self) -> None:
        layers = [
            {"name": "HLOD0", "layer_type": "simplified_mesh", "cell_size_m": 512, "loading_range_m": 1024},
            {"name": "HLOD1", "layer_type": "instancing", "cell_size_m": 2048, "loading_range_m": 4096},
        ]
        plans = ow.plan_hlod(8000, 256, layers)
        self.assertEqual([p.name for p in plans], ["HLOD0", "HLOD1"])
        self.assertEqual(plans[0].cells_per_axis, 16)
        self.assertEqual(plans[0].total_actors, 256)
        self.assertEqual(plans[0].cells_per_world_cell, 4.0)
        self.assertEqual(plans[1].cells_per_axis, 4)
        self.assertEqual(plans[1].total_actors, 16)
        self.assertEqual(plans[0].concurrent_actors, 21)

    def test_cell_misalignment_warns(self) -> None:
        plans = ow.plan_hlod(8000, 256, [
            {"name": "L0", "layer_type": "merged_mesh", "cell_size_m": 300, "loading_range_m": 1200},
        ])
        self.assertTrue(any("multiple" in w for w in plans[0].warnings))

    def test_range_smaller_than_two_cells_warns(self) -> None:
        plans = ow.plan_hlod(8000, 256, [
            {"name": "L0", "layer_type": "merged_mesh", "cell_size_m": 1024, "loading_range_m": 1500},
        ])
        self.assertTrue(any("pop in" in w for w in plans[0].warnings))

    def test_large_world_build_warning(self) -> None:
        plans = ow.plan_hlod(200_000, 256, [
            {"name": "L0", "layer_type": "instancing", "cell_size_m": 256, "loading_range_m": 1024},
        ])
        self.assertGreater(plans[0].total_actors, 50_000)
        self.assertTrue(any("rebuild" in w for w in plans[0].warnings))

    def test_invalid_layer_type(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.plan_hlod(8000, 256, [{"name": "L0", "layer_type": "magic", "cell_size_m": 512}])

    def test_empty_layers(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.plan_hlod(8000, 256, [])

    def test_build_time_scales_with_actor_count(self) -> None:
        plans = ow.plan_hlod(8000, 256, [
            {"name": "L0", "layer_type": "merged_mesh", "cell_size_m": 512, "loading_range_m": 1024},
        ], build_seconds_per_actor=3.0)
        self.assertAlmostEqual(plans[0].estimated_build_minutes, 256 * 3.0 / 60.0)


class ChecklistTest(unittest.TestCase):
    def test_all_todo_is_not_ready(self) -> None:
        statuses = {item.id: "todo" for item in ow.DEFAULT_CHECKLIST}
        report = ow.evaluate_checklist(statuses)
        self.assertFalse(report.ready)
        self.assertEqual(report.score, 0.0)
        self.assertEqual(report.todo, len(ow.DEFAULT_CHECKLIST))
        self.assertEqual(len(report.blockers), sum(1 for i in ow.DEFAULT_CHECKLIST if i.required))

    def test_all_pass_is_ready(self) -> None:
        statuses = {item.id: "pass" for item in ow.DEFAULT_CHECKLIST}
        report = ow.evaluate_checklist(statuses)
        self.assertTrue(report.ready)
        self.assertEqual(report.score, 100.0)
        self.assertFalse(report.blockers)

    def test_missing_item_counts_as_todo(self) -> None:
        statuses = {item.id: "pass" for item in ow.DEFAULT_CHECKLIST if item.id != "perf.budget"}
        report = ow.evaluate_checklist(statuses)
        self.assertFalse(report.ready)
        self.assertEqual(report.todo, 1)
        self.assertIn("perf.budget", report.blockers[0])

    def test_failed_required_blocks_and_lowers_score(self) -> None:
        statuses = {item.id: "pass" for item in ow.DEFAULT_CHECKLIST}
        statuses["terrain.size"] = "fail"
        report = ow.evaluate_checklist(statuses)
        self.assertFalse(report.ready)
        self.assertLess(report.score, 100.0)
        self.assertEqual(report.failed, 1)

    def test_skipped_required_still_blocks(self) -> None:
        statuses = {item.id: "pass" for item in ow.DEFAULT_CHECKLIST}
        statuses["lighting.vsm"] = "skip"
        report = ow.evaluate_checklist(statuses)
        self.assertFalse(report.ready)
        self.assertTrue(any("lighting.vsm" in b for b in report.blockers))

    def test_optional_skip_does_not_block(self) -> None:
        statuses = {item.id: "pass" for item in ow.DEFAULT_CHECKLIST}
        optional = [i.id for i in ow.DEFAULT_CHECKLIST if not i.required]
        self.assertTrue(optional)
        for item_id in optional:
            statuses[item_id] = "skip"
        report = ow.evaluate_checklist(statuses)
        self.assertTrue(report.ready)
        self.assertEqual(report.skipped, len(optional))

    def test_notes_are_kept(self) -> None:
        statuses = {item.id: "pass" for item in ow.DEFAULT_CHECKLIST}
        statuses["streaming.grid"] = {"status": "pass", "note": "256 m 셀, 히치 0"}
        report = ow.evaluate_checklist(statuses)
        self.assertEqual(report.notes["streaming.grid"], "256 m 셀, 히치 0")

    def test_unknown_ids_reported(self) -> None:
        report = ow.evaluate_checklist({"nope.id": "pass"})
        self.assertEqual(report.unknown_ids, ("nope.id",))

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.evaluate_checklist({"coord.lwc": "maybe"})

    def test_invalid_entry_type(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.evaluate_checklist({"coord.lwc": 3})

    def test_weights_are_used(self) -> None:
        items = (
            ow.CheckItem("a", "x", "A", "", weight=3),
            ow.CheckItem("b", "x", "B", "", weight=1),
        )
        report = ow.evaluate_checklist({"a": "pass", "b": "fail"}, items)
        self.assertAlmostEqual(report.score, 75.0)

    def test_every_category_has_items(self) -> None:
        categories = {i.category for i in ow.DEFAULT_CHECKLIST}
        self.assertEqual(
            categories,
            {"좌표계", "지형", "머티리얼", "스트리밍", "PCG", "인프라", "라이팅", "최적화", "빌드"},
        )

    def test_template_matches_checklist(self) -> None:
        template = ow.default_status_template()
        self.assertEqual(set(template["items"]), {i.id for i in ow.DEFAULT_CHECKLIST})
        self.assertEqual(template["engine_version"], "5.8")


class StatusFileTest(unittest.TestCase):
    def _write(self, payload: object) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with handle:
            json.dump(payload, handle)
        return Path(handle.name)

    def test_wrapped_and_bare_objects(self) -> None:
        wrapped = self._write({"items": {"coord.lwc": "pass"}})
        bare = self._write({"coord.lwc": "pass"})
        self.assertEqual(dict(ow.load_status_file(wrapped)), {"coord.lwc": "pass"})
        self.assertEqual(dict(ow.load_status_file(bare)), {"coord.lwc": "pass"})

    def test_missing_file(self) -> None:
        with self.assertRaises(ow.PlanError):
            ow.load_status_file(Path(tempfile.gettempdir()) / "no-such-open-world.json")

    def test_invalid_json(self) -> None:
        path = Path(tempfile.mkstemp(suffix=".json")[1])
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ow.PlanError):
            ow.load_status_file(path)

    def test_non_object_rejected(self) -> None:
        path = self._write([1, 2, 3])
        with self.assertRaises(ow.PlanError):
            ow.load_status_file(path)


class CliTest(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ow.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_grid_json(self) -> None:
        code, out, _ = self._run(["grid", "--world-km", "8", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["total_cells"], 1024)

    def test_grid_with_streaming(self) -> None:
        code, out, _ = self._run([
            "grid", "--world-km", "8", "--bytes-per-cell", "30000000", "--speed-mps", "6",
        ])
        self.assertEqual(code, 0)
        self.assertIn("로드 윈도우", out)
        self.assertIn("상주 추정", out)

    def test_landscape_text(self) -> None:
        code, out, _ = self._run(["landscape", "--target-m", "4000"])
        self.assertEqual(code, 0)
        self.assertIn("4033x4033", out)
        self.assertIn("1,024개", out)

    def test_landscape_error_exit_code(self) -> None:
        code, _, err = self._run(["landscape", "--target-m", "4000", "--quads-per-section", "64"])
        self.assertEqual(code, 1)
        self.assertIn("[error]", err)

    def test_rvt_text(self) -> None:
        code, out, _ = self._run([
            "rvt", "--world-m", "8129", "--texels-per-m", "0.5", "--layout", "base_color_normal",
        ])
        self.assertEqual(code, 0)
        self.assertIn("4096x4096", out)
        self.assertIn("24.0 MB", out)

    def test_hlod_default_layers(self) -> None:
        code, out, _ = self._run(["hlod", "--world-km", "8"])
        self.assertEqual(code, 0)
        self.assertIn("HLOD0", out)
        self.assertIn("HLOD1", out)

    def test_hlod_explicit_layer(self) -> None:
        code, out, _ = self._run([
            "hlod", "--world-km", "8", "--layer", "L0:merged_mesh:512:1024", "--json",
        ])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload[0]["layer_type"], "merged_mesh")
        self.assertEqual(payload[0]["total_actors"], 256)

    def test_hlod_bad_layer_format(self) -> None:
        code, _, err = self._run(["hlod", "--world-km", "8", "--layer", "L0:merged_mesh:512"])
        self.assertEqual(code, 1)
        self.assertIn("[error]", err)

    def test_checklist_print_default(self) -> None:
        code, out, _ = self._run(["checklist", "--print-default"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("coord.lwc", payload["items"])

    def test_checklist_from_file(self) -> None:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with handle:
            json.dump({"items": {i.id: "pass" for i in ow.DEFAULT_CHECKLIST}}, handle)
        code, out, _ = self._run(["checklist", "--status", handle.name])
        self.assertEqual(code, 0)
        self.assertIn("READY", out)

    def test_checklist_without_status_errors(self) -> None:
        with self.assertRaises(SystemExit):
            self._run(["checklist"])


if __name__ == "__main__":
    unittest.main()
