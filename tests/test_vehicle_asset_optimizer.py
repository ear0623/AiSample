"""차량 VRAM 예산·익스플로전·케이지 도구 테스트 (블렌더·엔진 없이 실행).

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

from pipeline import vehicle_asset_optimizer as va  # noqa: E402


class FormatTableTest(unittest.TestCase):
    """bpp 를 잘못 적으면 모든 예산 계산이 조용히 틀어진다."""

    def test_bc7_is_8_bits_per_pixel(self) -> None:
        self.assertEqual(va.get_format("bc7").bits_per_pixel, 8.0)
        self.assertEqual(va.get_format("bc7").bytes_per_block, 16)

    def test_bc5_matches_bc7_size(self) -> None:
        self.assertEqual(va.get_format("bc5").bits_per_pixel, va.get_format("bc7").bits_per_pixel)

    def test_bc1_and_bc4_are_half_of_bc7(self) -> None:
        self.assertEqual(va.get_format("bc1").bits_per_pixel, 4.0)
        self.assertEqual(va.get_format("bc4").bits_per_pixel, 4.0)

    def test_uncompressed_formats_are_not_block_compressed(self) -> None:
        self.assertFalse(va.get_format("r8").block_compressed)
        self.assertTrue(va.get_format("bc7").block_compressed)

    def test_format_lookup_is_case_insensitive(self) -> None:
        self.assertIs(va.get_format("BC7"), va.get_format("bc7"))

    def test_unknown_format_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.get_format("astc4x4")

    def test_ue_defaults_reference_known_formats(self) -> None:
        for key, fmt in va.UE_DEFAULT_FORMATS.items():
            with self.subTest(key=key):
                self.assertIn(fmt, va.FORMATS)


class TextureSizeTest(unittest.TestCase):
    def test_4096_bc7_base_is_16_mib(self) -> None:
        self.assertEqual(va.texture_bytes(4096, 4096, "bc7", mips=False), 16 * va.MIB)

    def test_4096_bc7_with_mips_is_21_33_mib(self) -> None:
        self.assertAlmostEqual(va.mib(va.texture_bytes(4096, 4096, "bc7")), 21.33, places=2)

    def test_mip_chain_adds_a_third(self) -> None:
        base = va.texture_bytes(4096, 4096, "bc5", mips=False)
        total = va.texture_bytes(4096, 4096, "bc5")
        self.assertAlmostEqual(total / base, 4 / 3, places=2)

    def test_mip_bytes_is_the_difference(self) -> None:
        total = va.texture_bytes(2048, 2048, "bc7")
        base = va.base_texture_bytes(2048, 2048, "bc7")
        self.assertEqual(base + va.mip_bytes(2048, 2048, "bc7"), total)
        self.assertAlmostEqual(va.mib(total), 5.33, places=2)

    def test_halving_resolution_quarters_the_size(self) -> None:
        big = va.texture_bytes(4096, 4096, "bc7")
        small = va.texture_bytes(2048, 2048, "bc7")
        self.assertAlmostEqual(big / small, 4.0, places=2)

    def test_bc1_is_half_of_bc7(self) -> None:
        self.assertEqual(
            va.texture_bytes(4096, 4096, "bc1"), va.texture_bytes(4096, 4096, "bc7") // 2
        )

    def test_smallest_mips_keep_one_block(self) -> None:
        # 2x2 도 1블록(16 B), 밉 2단이므로 32 B
        self.assertEqual(va.texture_bytes(2, 2, "bc7"), 32)
        self.assertEqual(va.texture_bytes(1, 1, "bc7"), 16)

    def test_r8_is_one_byte_per_pixel(self) -> None:
        self.assertEqual(va.texture_bytes(1024, 1024, "r8", mips=False), 1024 * 1024)

    def test_rgba8_is_four_bytes_per_pixel(self) -> None:
        self.assertEqual(va.texture_bytes(1024, 1024, "rgba8", mips=False), 4 * 1024 * 1024)

    def test_non_square_texture(self) -> None:
        self.assertEqual(
            va.texture_bytes(2048, 1024, "bc7", mips=False), 2048 * 1024
        )

    def test_zero_resolution_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.texture_bytes(0, 4096, "bc7")

    def test_float_resolution_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.texture_bytes(4096.5, 4096, "bc7")  # type: ignore[arg-type]


class MapSpecTest(unittest.TestCase):
    def test_count_multiplies(self) -> None:
        one = va.MapSpec("albedo", "bc7", 1024, 1024)
        three = va.MapSpec("albedo", "bc7", 1024, 1024, count=3)
        self.assertEqual(three.bytes(), one.bytes() * 3)

    def test_zero_count_is_empty(self) -> None:
        self.assertEqual(va.MapSpec("albedo", "bc7", 1024, 1024, count=0).bytes(), 0)

    def test_negative_count_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.MapSpec("albedo", "bc7", 1024, 1024, count=-1)

    def test_label_includes_resolution_and_format(self) -> None:
        label = va.MapSpec("normal", "bc5", 4096, 4096).label()
        self.assertIn("4096x4096", label)
        self.assertIn("BC5", label)

    def test_as_dict_rounds_mib(self) -> None:
        data = va.MapSpec("orm", "bc7", 4096, 4096).as_dict()
        self.assertAlmostEqual(data["mib"], 21.33, places=2)
        self.assertEqual(data["format"], "bc7")


class ParseMapSpecsTest(unittest.TestCase):
    def test_parses_default_layout(self) -> None:
        specs = va.parse_map_specs("normal=bc5,albedo=bc7,orm=bc7", 4096)
        self.assertEqual([s.name for s in specs], ["normal", "albedo", "orm"])
        self.assertEqual([s.fmt for s in specs], ["bc5", "bc7", "bc7"])
        self.assertTrue(all(s.width == 4096 for s in specs))

    def test_parses_count_suffix(self) -> None:
        specs = va.parse_map_specs("albedo=bc7:3", 2048)
        self.assertEqual(specs[0].count, 3)

    def test_tolerates_spaces(self) -> None:
        specs = va.parse_map_specs(" normal = bc5 , orm = bc7 ", 512)
        self.assertEqual(len(specs), 2)

    def test_missing_equals_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.parse_map_specs("normal:bc5", 4096)

    def test_bad_count_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.parse_map_specs("albedo=bc7:x", 4096)

    def test_empty_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.parse_map_specs(" , ", 4096)


class VehicleSetTest(unittest.TestCase):
    def test_default_sets_reproduce_the_80_mib_model(self) -> None:
        ext, itr = va.default_vehicle_sets(4096, 2048)
        self.assertAlmostEqual(ext.total_mib(), 64.0, places=2)
        self.assertAlmostEqual(itr.total_mib(), 16.0, places=2)

    def test_replace_swaps_a_map(self) -> None:
        ext, _ = va.default_vehicle_sets()
        swapped = ext.replace("orm", va.MapSpec("orm", "bc1", 4096, 4096))
        self.assertLess(swapped.total_bytes(), ext.total_bytes())

    def test_replace_with_none_removes(self) -> None:
        ext, _ = va.default_vehicle_sets()
        trimmed = ext.replace("normal", None)
        self.assertEqual(trimmed.map_names(), ("albedo", "orm"))

    def test_scaled_halves_resolution(self) -> None:
        _, itr = va.default_vehicle_sets()
        half = itr.scaled(0.5)
        self.assertEqual(half.find("normal").width, 1024)  # type: ignore[union-attr]
        self.assertLess(half.total_bytes(), itr.total_bytes())

    def test_scaled_rejects_non_positive(self) -> None:
        _, itr = va.default_vehicle_sets()
        with self.assertRaises(va.BudgetError):
            itr.scaled(0)

    def test_find_missing_returns_none(self) -> None:
        ext, _ = va.default_vehicle_sets()
        self.assertIsNone(ext.find("ao"))


class FleetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = va.analyze_fleet(chassis_count=18, fleet_size=2000)

    def test_per_model_is_80_mib(self) -> None:
        self.assertAlmostEqual(self.report.per_model_mib, 80.0, places=2)

    def test_eighteen_chassis_is_1440_mib(self) -> None:
        self.assertAlmostEqual(self.report.station_total_mib, 1440.0, places=2)

    def test_budget_ratio_is_about_14_percent(self) -> None:
        self.assertAlmostEqual(self.report.budget_ratio, 0.1406, places=3)
        self.assertEqual(self.report.verdict, "여유")

    def test_headroom_is_the_rest_of_ten_gib(self) -> None:
        self.assertAlmostEqual(self.report.headroom_mib, 8800.0, places=1)

    def test_textures_depend_on_chassis_not_fleet_size(self) -> None:
        two_thousand = va.analyze_fleet(chassis_count=18, fleet_size=2000).station_total_mib
        ten_thousand = va.analyze_fleet(chassis_count=18, fleet_size=10000).station_total_mib
        self.assertEqual(two_thousand, ten_thousand)

    def test_instance_buffer_scales_with_fleet(self) -> None:
        self.assertAlmostEqual(self.report.instance_buffer_mib, 0.49, places=2)
        big = va.analyze_fleet(chassis_count=18, fleet_size=4000, instance_bytes=256)
        self.assertAlmostEqual(big.instance_buffer_mib, self.report.instance_buffer_mib * 2, places=3)

    def test_more_chassis_scales_linearly(self) -> None:
        forty = va.analyze_fleet(chassis_count=40)
        self.assertAlmostEqual(forty.station_total_mib / self.report.station_total_mib, 40 / 18, places=4)

    def test_no_mips_is_cheaper(self) -> None:
        base_only = va.analyze_fleet(chassis_count=18, mips=False)
        self.assertAlmostEqual(base_only.per_model_mib, 60.0, places=2)
        self.assertLess(base_only.station_total_mib, self.report.station_total_mib)

    def test_tight_budget_changes_verdict(self) -> None:
        tight = va.analyze_fleet(chassis_count=18, budget_mib=3000)
        self.assertEqual(tight.verdict, "주의")

    def test_over_budget_verdict(self) -> None:
        over = va.analyze_fleet(chassis_count=18, budget_mib=2000)
        self.assertEqual(over.verdict, "초과")

    def test_verdict_thresholds(self) -> None:
        self.assertEqual(va.budget_verdict(0.1), "여유")
        self.assertEqual(va.budget_verdict(0.25), "적정")
        self.assertEqual(va.budget_verdict(0.45), "주의")
        self.assertEqual(va.budget_verdict(0.9), "초과")

    def test_custom_sets_are_respected(self) -> None:
        ext = va.VehicleSet("ext", (va.MapSpec("albedo", "bc1", 1024, 1024),))
        itr = va.VehicleSet("int", (va.MapSpec("albedo", "bc1", 512, 512),))
        report = va.analyze_fleet(1, 100, ext, itr, budget_mib=1024)
        self.assertAlmostEqual(report.per_model_mib, ext.total_mib() + itr.total_mib(), places=3)

    def test_zero_chassis_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.analyze_fleet(chassis_count=0)

    def test_negative_fleet_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.analyze_fleet(fleet_size=-1)

    def test_zero_budget_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.analyze_fleet(budget_mib=0)

    def test_scenarios_include_interior_half(self) -> None:
        self.assertIn("interior_half", self.report.scenarios)
        delta = self.report.scenarios["interior_half"]["delta_mib"]
        self.assertGreater(delta, 0)

    def test_orm_unpacking_costs_more_than_packing(self) -> None:
        delta = self.report.scenarios["orm_unpacked"]["delta_mib"]
        self.assertLess(delta, 0)

    def test_notes_mention_unit_and_chassis_sharing(self) -> None:
        joined = " ".join(self.report.notes)
        self.assertIn("MiB", joined)
        self.assertIn("차종 수", joined)

    def test_as_dict_is_json_serialisable(self) -> None:
        payload = json.dumps(self.report.as_dict(), ensure_ascii=False)
        self.assertIn("station_total_mib", payload)


class PackingTest(unittest.TestCase):
    def test_three_bc7_maps_to_one_saves_two_thirds(self) -> None:
        report = va.packing_comparison(4096, separate_fmt="bc7")
        self.assertAlmostEqual(report.saving_pct * 100, 66.7, places=1)

    def test_bc4_greyscale_alternative_saves_a_third(self) -> None:
        report = va.packing_comparison(4096, separate_fmt="bc4")
        self.assertAlmostEqual(report.saving_pct * 100, 33.3, places=1)

    def test_packed_equals_one_map(self) -> None:
        report = va.packing_comparison(2048)
        self.assertEqual(report.packed_bytes, va.texture_bytes(2048, 2048, "bc7"))

    def test_saving_ratio_is_resolution_independent(self) -> None:
        a = va.packing_comparison(1024).saving_pct
        b = va.packing_comparison(4096).saving_pct
        self.assertAlmostEqual(a, b, places=6)

    def test_as_dict_reports_pct(self) -> None:
        data = va.packing_comparison(512).as_dict()
        self.assertAlmostEqual(data["saving_pct"], 66.7, places=1)


class PartBoxTest(unittest.TestCase):
    def test_from_dict_accepts_min_max_alias(self) -> None:
        box = va.PartBox.from_dict({"name": "hood", "min": [0, 0, 0], "max": [1, 1, 1]})
        self.assertEqual(box.hi, (1.0, 1.0, 1.0))

    def test_inverted_box_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.PartBox("bad", (0, 0, 1), (1, 1, 0))

    def test_bad_vector_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.PartBox.from_dict({"name": "x", "lo": [0, 0], "hi": [1, 1, 1]})

    def test_size_and_center(self) -> None:
        box = va.PartBox("seat", (0, 0, 0.2), (0.6, 0.6, 0.5))
        self.assertAlmostEqual(box.size("z"), 0.3)
        self.assertAlmostEqual(box.center("z"), 0.35)


class ExplosionTest(unittest.TestCase):
    def test_demo_parts_end_up_separated(self) -> None:
        plan = va.plan_explosion(va.DEMO_PARTS, axis="z", gap=0.02)
        self.assertEqual(plan.overlaps(), [])
        self.assertEqual(len(plan.entries), len(va.DEMO_PARTS))

    def test_first_member_of_group_stays_put(self) -> None:
        plan = va.plan_explosion(va.DEMO_PARTS, axis="z", gap=0.02)
        first = min(plan.entries, key=lambda e: e.lo)
        self.assertAlmostEqual(first.new_lo, first.lo)

    def test_offset_only_along_chosen_axis(self) -> None:
        plan = va.plan_explosion(va.DEMO_PARTS, axis="x", gap=0.01)
        for entry in plan.entries:
            others = [i for i in range(3) if i != va.AXIS_INDEX["x"]]
            for i in others:
                self.assertEqual(entry.offset[i], 0.0)

    def test_gap_widens_the_spacing(self) -> None:
        tight = va.plan_explosion(va.DEMO_PARTS, axis="z", gap=0.0)
        wide = va.plan_explosion(va.DEMO_PARTS, axis="z", gap=0.1)
        self.assertGreater(wide.max_distance, tight.max_distance)

    def test_disjoint_parts_are_untouched(self) -> None:
        parts = (
            va.PartBox("a", (0, 0, 0.0), (1, 1, 0.1)),
            va.PartBox("b", (0, 0, 0.5), (1, 1, 0.6)),
        )
        plan = va.plan_explosion(parts, axis="z", gap=0.05)
        self.assertEqual(plan.groups, 2)
        self.assertEqual(plan.displaced, 0)

    def test_touching_parts_are_grouped(self) -> None:
        parts = (
            va.PartBox("a", (0, 0, 0.0), (1, 1, 0.5)),
            va.PartBox("b", (0, 0, 0.5), (1, 1, 1.0)),
        )
        plan = va.plan_explosion(parts, axis="z", gap=0.0)
        self.assertEqual(plan.groups, 1)
        self.assertEqual(plan.overlaps(), [])

    def test_single_part_needs_no_move(self) -> None:
        plan = va.plan_explosion((va.PartBox("only", (0, 0, 0), (1, 1, 1)),), axis="z", gap=0.1)
        self.assertEqual(plan.max_distance, 0.0)
        self.assertEqual(plan.displaced, 0)

    def test_input_order_does_not_change_the_result(self) -> None:
        forward = va.plan_explosion(va.DEMO_PARTS, axis="z", gap=0.02)
        backward = va.plan_explosion(tuple(reversed(va.DEMO_PARTS)), axis="z", gap=0.02)
        self.assertEqual(
            {e.name: round(e.new_lo, 6) for e in forward.entries},
            {e.name: round(e.new_lo, 6) for e in backward.entries},
        )

    def test_empty_input(self) -> None:
        plan = va.plan_explosion((), axis="z")
        self.assertEqual(plan.entries, ())
        self.assertEqual(plan.groups, 0)

    def test_bad_axis_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.plan_explosion(va.DEMO_PARTS, axis="w")

    def test_negative_gap_raises(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.plan_explosion(va.DEMO_PARTS, gap=-0.01)

    def test_as_dict_converts_units(self) -> None:
        plan = va.plan_explosion(va.DEMO_PARTS, axis="z", gap=0.02)
        data = plan.as_dict("mm")
        self.assertEqual(data["unit"], "mm")
        self.assertAlmostEqual(data["gap"] * 1000, 20.0, places=6)
        self.assertEqual(data["residual_overlaps"], [])


class CageTest(unittest.TestCase):
    def test_good_cage_passes(self) -> None:
        report = va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_GOOD)
        self.assertEqual(report.verdict, "OK")
        self.assertFalse(report.failed)

    def test_tight_cage_warns(self) -> None:
        report = va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_TIGHT)
        self.assertEqual(report.verdict, "WARN")
        keys = {c.key: c.status for c in report.checks}
        self.assertEqual(keys["margin"], "WARN")

    def test_bad_cage_fails(self) -> None:
        report = va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_BAD)
        self.assertEqual(report.verdict, "FAIL")
        self.assertEqual(report.exposed_axes, ("y",))

    def test_topology_mismatch_fails(self) -> None:
        cage = va.MeshProbe("cage", (-0.7, -0.02, 0.09), (0.7, 0.11, 0.71), 999)
        report = va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, cage)
        self.assertTrue(report.failed)
        self.assertEqual(next(c for c in report.checks if c.key == "topology").status, "FAIL")

    def test_cage_smaller_than_low_warns(self) -> None:
        cage = va.MeshProbe("cage", (-0.59, 0.0, 0.10), (0.59, 0.11, 0.70), 1840)
        report = va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, cage)
        keys = {c.key: c.status for c in report.checks}
        self.assertEqual(keys["outside_low"], "WARN")

    def test_high_inside_low_warns_about_silhouette(self) -> None:
        low = va.MeshProbe("low", (-1, -1, -1), (1, 1, 1), 500)
        high = va.MeshProbe("high", (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 9000)
        cage = va.MeshProbe("cage", (-1.2, -1.2, -1.2), (1.2, 1.2, 1.2), 500)
        report = va.validate_cage(low, high, cage)
        self.assertEqual(next(c for c in report.checks if c.key == "silhouette").status, "WARN")

    def test_margins_are_positive_for_good_cage(self) -> None:
        report = va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_GOOD)
        self.assertTrue(all(m > 0 for m in report.margins))
        self.assertAlmostEqual(report.min_margin, 0.01, places=3)

    def test_min_margin_bounds_are_validated(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_GOOD, min_margin_ratio=-0.1)
        with self.assertRaises(va.BudgetError):
            va.validate_cage(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_GOOD,
                             min_margin_ratio=0.5, max_margin_ratio=0.2)

    def test_zero_verts_skips_topology(self) -> None:
        low = va.MeshProbe("low", (-0.6, 0, 0.1), (0.6, 0.08, 0.7), 0)
        probe = va.MeshProbe("cage", (-0.612, -0.018, 0.092), (0.612, 0.116, 0.708), 0)
        report = va.validate_cage(low, va.DEMO_HIGH, probe)
        self.assertEqual(next(c for c in report.checks if c.key == "topology").status, "INFO")

    def test_cavity_risk_hints_for_thick_balloon(self) -> None:
        hints = va.cavity_risk(va.DEMO_LOW, va.DEMO_HIGH, va.DEMO_CAGE_GOOD)
        self.assertIsInstance(hints, list)

    def test_probe_from_dict(self) -> None:
        probe = va.MeshProbe.from_dict({"name": "x", "lo": [0, 0, 0], "hi": [1, 1, 1], "verts": 12})
        self.assertEqual(probe.verts, 12)

    def test_negative_verts_raise(self) -> None:
        with self.assertRaises(va.BudgetError):
            va.MeshProbe.from_dict({"name": "x", "lo": [0, 0, 0], "hi": [1, 1, 1], "verts": -3})


class CliTest(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = va.main(argv)
            except SystemExit as exc:  # argparse 오류
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_vram_default_matches_the_guide(self) -> None:
        code, out, _ = self.run_cli(["vram", "--chassis", "18", "--exterior", "4096", "--interior", "2048"])
        self.assertEqual(code, 0)
        self.assertIn("1,440.0 MiB", out)
        self.assertIn("14.1%", out)
        self.assertIn("0.49 MiB", out)

    def test_vram_json(self) -> None:
        code, out, _ = self.run_cli(["vram", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["chassis_count"], 18)
        self.assertAlmostEqual(data["per_model_mib"], 80.0, places=2)

    def test_vram_no_mips(self) -> None:
        _, out, _ = self.run_cli(["vram", "--no-mips"])
        self.assertIn("1,080.0 MiB", out)

    def test_vram_custom_maps(self) -> None:
        code, out, _ = self.run_cli(["vram", "--exterior-maps", "albedo=bc1,normal=bc5", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["exterior"]["maps"]), 2)

    def test_vram_bad_map_spec_exits_nonzero(self) -> None:
        code, _, err = self.run_cli(["vram", "--exterior-maps", "albedo"])
        self.assertEqual(code, 1)
        self.assertIn("[error]", err)

    def test_formats_lists_bc7(self) -> None:
        code, out, _ = self.run_cli(["formats"])
        self.assertEqual(code, 0)
        self.assertIn("BC7", out)
        self.assertIn("21.33 MiB", out)

    def test_packing_cli(self) -> None:
        code, out, _ = self.run_cli(["packing", "--resolution", "4096"])
        self.assertEqual(code, 0)
        self.assertIn("66.7%", out)

    def test_explode_demo_exit_zero(self) -> None:
        code, out, _ = self.run_cli(["explode", "--demo", "--axis", "z", "--gap", "0.02"])
        self.assertEqual(code, 0)
        self.assertIn("잔여 겹침 0쌍", out)

    def test_explode_requires_input(self) -> None:
        code, _, _ = self.run_cli(["explode"])
        self.assertEqual(code, 2)

    def test_explode_from_json_file(self) -> None:
        payload = {"objects": [
            {"name": "cushion", "lo": [0, 0, 0.2], "hi": [0.5, 0.5, 0.4]},
            {"name": "frame", "lo": [0, 0, 0.1], "hi": [0.5, 0.5, 0.35]},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, out, _ = self.run_cli(["explode", "--json", str(path), "--dump-json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(data["residual_overlaps"], [])

    def test_missing_json_file_reports_error(self) -> None:
        code, _, err = self.run_cli(["explode", "--json", "/nonexistent/scene.json"])
        self.assertEqual(code, 1)
        self.assertIn("찾을 수 없다", err)

    def test_cage_demo(self) -> None:
        code, out, _ = self.run_cli(["cage", "--demo"])
        self.assertEqual(code, 0)
        self.assertIn("케이지 검증 —", out)
        self.assertIn("FAIL", out)

    def test_cage_json_pass(self) -> None:
        payload = {
            "low": {"name": "l", "lo": [-0.6, 0.0, 0.1], "hi": [0.6, 0.08, 0.7], "verts": 1840},
            "high": {"name": "h", "lo": [-0.6, -0.01, 0.1], "hi": [0.6, 0.10, 0.7], "verts": 412000},
            "cage": {"name": "c", "lo": [-0.612, -0.018, 0.092], "hi": [0.612, 0.116, 0.708], "verts": 1840},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cage.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, out, _ = self.run_cli(["cage", "--json", str(path), "--dump-json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "OK")

    def test_cage_json_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cage.json"
            path.write_text(json.dumps({"low": {"lo": [0, 0, 0], "hi": [1, 1, 1]}}), encoding="utf-8")
            code, _, err = self.run_cli(["cage", "--json", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("high", err)

    def test_checklist_has_twelve_steps(self) -> None:
        code, out, _ = self.run_cli(["checklist"])
        self.assertEqual(code, 0)
        numbered = [line for line in out.splitlines()
                    if line.strip()[:3].strip().rstrip(".").isdigit()]
        self.assertEqual(len(numbered), 12)
        self.assertIn("3c", out)


class DocConsistencyTest(unittest.TestCase):
    """문서와 코드가 서로를 가리키지 않으면 독자는 둘 다 못 쓴다."""

    DOC = ROOT / "docs" / "blender_asset_production_troubleshooting_guide.md"

    def test_doc_exists(self) -> None:
        self.assertTrue(self.DOC.exists())

    def test_doc_has_the_four_chapters(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        for heading in ("LP", "베이킹", "VRAM", "체크리스트"):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)

    def test_doc_references_the_module(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        self.assertIn("pipeline/vehicle_asset_optimizer.py", text)

    def test_module_docstring_points_to_the_doc(self) -> None:
        self.assertIn("blender_asset_production_troubleshooting_guide.md", va.__doc__ or "")

    def test_readme_links_doc_and_module(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("blender_asset_production_troubleshooting_guide.md", readme)
        self.assertIn("vehicle_asset_optimizer.py", readme)

    def test_doc_quotes_the_numbers_the_code_computes(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        self.assertIn("21.33", text)
        self.assertIn("1,440", text)
        self.assertIn("66.7", text)


if __name__ == "__main__":
    unittest.main()
