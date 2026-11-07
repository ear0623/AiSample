"""실내 탐사 수치 계산기 테스트 (엔진·네트워크 없이 실행).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import math
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import indoor_metric_helper as im  # noqa: E402


class EngineDefaultsTest(unittest.TestCase):
    """엔진 기본값을 잘못 옮겨 적으면 모든 계산이 조용히 틀어진다."""

    def test_capsule_defaults(self) -> None:
        self.assertEqual(im.DEFAULT_CAPSULE_RADIUS, 34.0)
        self.assertEqual(im.DEFAULT_CAPSULE_HALF_HEIGHT * 2, 176.0)

    def test_eye_height_default_is_152(self) -> None:
        # 88(반높이) + 64(BaseEyeHeight)
        report = im.analyze_space(240, 130, 240, 400)
        self.assertEqual(report.eye_height, 152.0)

    def test_cmc_thresholds(self) -> None:
        self.assertEqual(im.DEFAULT_MAX_STEP_HEIGHT, 45.0)
        self.assertAlmostEqual(im.DEFAULT_WALKABLE_FLOOR_ANGLE, 44.765, places=3)

    def test_unit_is_centimeter(self) -> None:
        self.assertEqual(im.UE_UNITS_PER_METER, 100.0)


class CameraClearanceTest(unittest.TestCase):
    def test_narrow_residential_corridor_squeezes_camera(self) -> None:
        cam = im.camera_clearance(180, 300, arm_length=220, pitch_deg=15)
        # 좌우 여유 90-12=78, 수평 도달 220*cos15=212.5 -> asin(0.367)=21.5도
        self.assertAlmostEqual(cam.lateral_budget, 78.0, places=2)
        self.assertAlmostEqual(cam.lateral_reach, 212.5, places=1)
        self.assertAlmostEqual(cam.free_yaw_deg, 21.53, places=1)
        self.assertLess(cam.allowed_arm, im.MIN_USABLE_ARM)
        self.assertEqual(cam.mode, "first_person")

    def test_wide_hall_keeps_full_arm(self) -> None:
        cam = im.camera_clearance(1000, 600, arm_length=200, pitch_deg=10)
        self.assertEqual(cam.allowed_arm, 200.0)
        self.assertEqual(cam.retract_ratio, 0.0)
        self.assertEqual(cam.mode, "full_orbit")
        self.assertEqual(cam.free_yaw_deg, 90.0)

    def test_ceiling_limits_upward_pitch(self) -> None:
        low = im.camera_clearance(800, 220, arm_length=220, pitch_deg=15)
        tall = im.camera_clearance(800, 500, arm_length=220, pitch_deg=15)
        self.assertLess(low.vertical_budget, tall.vertical_budget)
        self.assertLess(low.allowed_arm, tall.allowed_arm)
        self.assertLess(low.free_pitch_deg, tall.free_pitch_deg)

    def test_free_pitch_matches_geometry(self) -> None:
        cam = im.camera_clearance(400, 300, arm_length=220, pitch_deg=15, eye_height=152)
        # (300-152-12)/220 = 0.618 -> 38.2도
        self.assertAlmostEqual(cam.free_pitch_deg, 38.18, places=1)

    def test_probe_size_shrinks_budget(self) -> None:
        small = im.camera_clearance(240, 350, arm_length=240, probe_size=8)
        large = im.camera_clearance(240, 350, arm_length=240, probe_size=20)
        self.assertGreater(small.lateral_budget, large.lateral_budget)
        self.assertGreaterEqual(small.free_yaw_deg, large.free_yaw_deg)

    def test_shoulder_offset_is_subtracted(self) -> None:
        base = im.camera_clearance(240, 350, arm_length=240, shoulder_offset=0)
        shifted = im.camera_clearance(240, 350, arm_length=240, shoulder_offset=30)
        self.assertAlmostEqual(shifted.lateral_budget, base.lateral_budget - 30.0, places=2)
        self.assertLess(shifted.free_yaw_deg, base.free_yaw_deg)

    def test_negative_pitch_uses_floor_budget(self) -> None:
        # 아래를 보면 카메라가 피벗 아래로 내려간다 -> 바닥까지 남은 눈높이가 한계
        cam = im.camera_clearance(400, 600, arm_length=300, pitch_deg=-30, eye_height=152)
        expected = (152 - 12) / math.sin(math.radians(30))
        self.assertAlmostEqual(cam.allowed_arm_vertical, expected, places=1)

    def test_warnings_fire_on_tight_corridor(self) -> None:
        cam = im.camera_clearance(150, 280, arm_length=260, pitch_deg=15)
        self.assertTrue(cam.warnings)
        self.assertTrue(any("회전 여유" in w for w in cam.warnings))

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(im.MetricError):
            im.camera_clearance(0, 300)
        with self.assertRaises(im.MetricError):
            im.camera_clearance(200, 0)
        with self.assertRaises(im.MetricError):
            im.camera_clearance(200, 300, arm_length=0)
        with self.assertRaises(im.MetricError):
            im.camera_clearance(200, 300, probe_size=0)


class AnalyzeSpaceTest(unittest.TestCase):
    def test_office_preset_passes_body_checks(self) -> None:
        report = im.analyze_space(240, 130, 240, 400, preset="office_lab")
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["corridor.passable"].status, "pass")
        self.assertEqual(by_key["corridor.passing"].status, "pass")
        self.assertEqual(by_key["door.clearance"].status, "pass")
        self.assertEqual(by_key["ceiling.height"].status, "pass")

    def test_actual_90cm_door_fails_game_clearance(self) -> None:
        report = im.analyze_space(240, 90, 220, 300)
        by_key = {c.key: c for c in report.checks}
        # 90 - 68 = 22 cm: 통과는 되지만 여유가 25 cm 미만
        self.assertEqual(by_key["door.clearance"].value, 22.0)
        self.assertEqual(by_key["door.clearance"].status, "fail")
        self.assertTrue(by_key["door.clearance"].blocking)

    def test_tiny_corridor_is_not_explorable(self) -> None:
        report = im.analyze_space(80, 90, 210, 240)
        self.assertEqual(report.verdict, "탐사 불가")

    def test_low_ceiling_warns(self) -> None:
        report = im.analyze_space(240, 120, 220, 220)
        by_key = {c.key: c for c in report.checks}
        self.assertIn(by_key["ceiling.height"].status, ("warn", "fail"))

    def test_ue_default_crouch_is_flagged(self) -> None:
        report = im.analyze_space(240, 130, 240, 400, crouch_height=80.0)
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["crouch.fit"].status, "fail")

    def test_recommended_crouch_passes(self) -> None:
        report = im.analyze_space(240, 130, 240, 400)
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["crouch.fit"].status, "pass")

    def test_scores_are_bounded(self) -> None:
        for corridor in (80, 150, 240, 400, 1200):
            report = im.analyze_space(corridor, 130, 240, 350)
            self.assertGreaterEqual(report.comfort, 0.0)
            self.assertLessEqual(report.comfort, 100.0)
            self.assertGreaterEqual(report.clipping_risk, 0.0)
            self.assertLessEqual(report.clipping_risk, 100.0)

    def test_comfort_grows_with_corridor_width(self) -> None:
        narrow = im.analyze_space(180, 120, 230, 300, arm_length=220)
        wide = im.analyze_space(400, 120, 230, 300, arm_length=220)
        self.assertLess(narrow.comfort, wide.comfort)

    def test_verdict_downgrades_on_any_failure(self) -> None:
        # 쾌적도는 높지만 천장이 낮아 카메라 검사가 실패하는 조합
        report = im.analyze_space(600, 200, 280, 200, arm_length=200)
        self.assertTrue(report.failures)
        self.assertNotIn(report.verdict, ("권장", "양호"))

    def test_check_keys_are_unique(self) -> None:
        report = im.analyze_space(240, 130, 240, 400, stair_riser=17, stair_tread=29)
        keys = [c.key for c in report.checks]
        self.assertEqual(len(keys), len(set(keys)))

    def test_stair_checks_included_when_given(self) -> None:
        report = im.analyze_space(240, 130, 240, 400, stair_riser=17, stair_tread=29)
        keys = {c.key for c in report.checks}
        self.assertIn("stair.blondel", keys)
        self.assertIn("stair.code", keys)

    def test_stair_checks_absent_by_default(self) -> None:
        report = im.analyze_space(240, 130, 240, 400)
        keys = {c.key for c in report.checks}
        self.assertNotIn("stair.blondel", keys)

    def test_invalid_space_inputs(self) -> None:
        with self.assertRaises(im.MetricError):
            im.analyze_space(0, 130, 240, 400)
        with self.assertRaises(im.MetricError):
            im.analyze_space(240, -1, 240, 400)
        with self.assertRaises(im.MetricError):
            im.analyze_space(240, 130, 240, 400, capsule_radius=0)

    def test_json_round_trip(self) -> None:
        report = im.analyze_space(240, 130, 240, 400)
        payload = json.loads(json.dumps(report.as_dict(), ensure_ascii=False))
        self.assertEqual(payload["verdict"], report.verdict)
        self.assertIn("free_yaw_deg", payload["camera"])
        self.assertEqual(len(payload["checks"]), len(report.checks))


class StairTest(unittest.TestCase):
    def test_ideal_domestic_stair(self) -> None:
        report = im.check_stairs(18, 28)
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["stair.blondel"].status, "pass")
        self.assertEqual(by_key["stair.code"].status, "pass")
        self.assertEqual(by_key["stair.slope"].status, "pass")
        self.assertAlmostEqual(report.ratio, 64.0)
        self.assertAlmostEqual(report.angle_deg, 32.74, places=2)

    def test_twenty_one_square_passes_blondel_but_not_code(self) -> None:
        report = im.check_stairs(21, 21)
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["stair.blondel"].status, "pass")   # 2R+T = 63
        self.assertEqual(by_key["stair.code"].status, "fail")      # 단높이 18 초과
        self.assertEqual(by_key["stair.cmc"].status, "fail")       # 45도 > 44.765

    def test_shallow_stairs_fail_blondel(self) -> None:
        report = im.check_stairs(10, 25)
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["stair.blondel"].status, "fail")   # 45 cm

    def test_step_count_and_actual_riser(self) -> None:
        report = im.check_stairs(18, 28, floor_height=320)
        self.assertEqual(report.steps, 18)
        self.assertAlmostEqual(report.run_cm, 504.0)
        # 320/18 = 17.78 -> 18단이면 실제 단높이는 17.8
        self.assertEqual(report.landings, 1)

    def test_three_meter_floor_needs_no_landing(self) -> None:
        report = im.check_stairs(18, 28, floor_height=300)
        self.assertEqual(report.landings, 0)

    def test_steep_stair_beyond_step_height(self) -> None:
        report = im.check_stairs(48, 30)
        keys = {c.key for c in report.checks}
        self.assertIn("stair.step", keys)

    def test_headroom_and_width(self) -> None:
        report = im.check_stairs(18, 28, width=110, headroom=200)
        by_key = {c.key: c for c in report.checks}
        self.assertEqual(by_key["stair.headroom"].status, "fail")
        self.assertEqual(by_key["stair.width"].status, "fail")

    def test_score_drops_with_violations(self) -> None:
        good = im.check_stairs(17, 29)
        bad = im.check_stairs(21, 21)
        self.assertGreater(good.score, bad.score)

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(im.MetricError):
            im.check_stairs(0, 28)
        with self.assertRaises(im.MetricError):
            im.check_stairs(18, 0)
        with self.assertRaises(im.MetricError):
            im.check_stairs(18, 28, floor_height=0)


class ClutterTest(unittest.TestCase):
    def test_density_grades_are_ordered(self) -> None:
        counts = [im.clutter_budget(40, g).props for g in ("sparse", "normal", "dense", "cluttered")]
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(len(set(counts)), 4)

    def test_nanite_uses_ism(self) -> None:
        self.assertEqual(im.clutter_budget(40, "normal", nanite=True).component, "ISM")

    def test_non_nanite_uses_hism(self) -> None:
        self.assertEqual(im.clutter_budget(40, "normal", nanite=False).component, "HISM")

    def test_variants_never_exceed_props(self) -> None:
        for area in (4, 12, 40, 200):
            budget = im.clutter_budget(area, "cluttered")
            self.assertLessEqual(budget.variants, budget.props)

    def test_triangle_estimate_matches_props(self) -> None:
        budget = im.clutter_budget(40, "dense")
        self.assertEqual(budget.triangles, round(budget.props * budget.avg_tris))

    def test_cluttered_tiny_room_warns(self) -> None:
        budget = im.clutter_budget(12, "cluttered")
        self.assertTrue(any("통행" in w for w in budget.warnings))

    def test_huge_triangle_budget_warns(self) -> None:
        budget = im.clutter_budget(120, "cluttered")
        self.assertTrue(any("1.2M" in w or "삼각형" in w for w in budget.warnings))

    def test_unknown_grade(self) -> None:
        with self.assertRaises(im.MetricError):
            im.clutter_budget(40, "insane")

    def test_invalid_area(self) -> None:
        with self.assertRaises(im.MetricError):
            im.clutter_budget(0)


class PresetTest(unittest.TestCase):
    def test_expected_presets_exist(self) -> None:
        for key in ("residential", "office_lab", "commercial", "dungeon_bunker", "industrial"):
            self.assertIn(key, im.PRESETS)

    def test_preset_internal_ordering(self) -> None:
        for preset in im.PRESETS.values():
            self.assertLess(preset.corridor_min, preset.corridor_standard)
            self.assertLess(preset.corridor_standard, preset.corridor_wide)
            self.assertLess(preset.door_width, preset.double_door_width)
            self.assertLess(preset.ceiling, preset.floor_to_floor)
            self.assertGreater(preset.stair_width, preset.door_width)

    def test_every_preset_stair_meets_blondel(self) -> None:
        for preset in im.PRESETS.values():
            ratio = 2 * preset.stair_riser + preset.stair_tread
            self.assertGreaterEqual(ratio, im.BLONDEL_MIN, preset.key)
            self.assertLessEqual(ratio, im.BLONDEL_MAX, preset.key)

    def test_every_preset_stair_meets_korean_code(self) -> None:
        for preset in im.PRESETS.values():
            self.assertLessEqual(preset.stair_riser, im.KOREAN_MAX_RISER, preset.key)
            self.assertGreaterEqual(preset.stair_tread, im.KOREAN_MIN_TREAD, preset.key)

    def test_every_preset_has_viable_camera(self) -> None:
        for preset in im.PRESETS.values():
            cam = im.camera_clearance(
                preset.corridor_standard, preset.ceiling, arm_length=preset.camera_arm
            )
            self.assertGreaterEqual(cam.free_yaw_deg, 20.0, preset.key)

    def test_unknown_preset(self) -> None:
        with self.assertRaises(im.MetricError):
            im.get_preset("space_station")

    def test_resolve_spec_uses_overrides(self) -> None:
        spec = im.resolve_spec("office_lab", {"corridor_width": 200.0})
        self.assertEqual(spec["corridor_width"], 200.0)
        self.assertEqual(spec["door_width"], im.PRESETS["office_lab"].door_width)

    def test_resolve_spec_ignores_none(self) -> None:
        spec = im.resolve_spec("office_lab", {"corridor_width": None})
        self.assertEqual(spec["corridor_width"], im.PRESETS["office_lab"].corridor_standard)


class CliTest(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = im.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_presets_text(self) -> None:
        code, out, _ = self._run(["presets"])
        self.assertEqual(code, 0)
        self.assertIn("office_lab", out)
        self.assertIn("복도", out)

    def test_preset_json(self) -> None:
        code, out, _ = self._run(["preset", "--type", "dungeon_bunker", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["key"], "dungeon_bunker")
        self.assertEqual(payload["ceiling"], 350.0)

    def test_check_json(self) -> None:
        code, out, _ = self._run(["check", "--preset", "residential", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["preset"], "residential")
        self.assertIn("verdict", payload)
        self.assertTrue(payload["checks"])

    def test_check_with_overrides(self) -> None:
        code, out, _ = self._run(["check", "--preset", "office_lab", "--corridor", "180", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["corridor_width"], 180.0)

    def test_camera_text(self) -> None:
        code, out, _ = self._run(["camera", "--corridor", "180", "--ceiling", "300", "--arm", "220"])
        self.assertEqual(code, 0)
        self.assertIn("좌우 회전 한계", out)
        self.assertIn("허용 암 길이", out)

    def test_stairs_json(self) -> None:
        code, out, _ = self._run(["stairs", "--riser", "18", "--tread", "28", "--floor-height", "320", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["steps"], 18)
        self.assertEqual(payload["ratio"], 64.0)

    def test_clutter_no_nanite(self) -> None:
        code, out, _ = self._run(["clutter", "--area", "40", "--grade", "dense", "--no-nanite", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["component"], "HISM")

    def test_invalid_value_exits_one(self) -> None:
        code, _, err = self._run(["camera", "--corridor", "0", "--ceiling", "300"])
        self.assertEqual(code, 1)
        self.assertIn("[error]", err)

    def test_unknown_clutter_grade_rejected_by_parser(self) -> None:
        with self.assertRaises(SystemExit):
            self._run(["clutter", "--area", "40", "--grade", "nope"])

    def test_unknown_preset_rejected_by_parser(self) -> None:
        with self.assertRaises(SystemExit):
            self._run(["check", "--preset", "space_station"])


if __name__ == "__main__":
    unittest.main()
