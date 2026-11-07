#!/usr/bin/env python3
"""인게임 실내 탐사 공간 수치 계산기 — 복도·문·층고·계단·카메라 붐·소품 밀도.

실내 탐사에서 "느낌"을 만드는 것은 조명과 소품이지만, 그 느낌이 성립하려면
먼저 **플레이어가 지나갈 수 있고 카메라가 벽을 뚫지 않는 치수**가 있어야 한다.
실외에서는 300 cm 복도와 120 cm 문이 그럭저럭 돌아가지만, 3인칭 카메라가
복도를 따라 회전하는 순간 같은 수치가 화면을 무너뜨린다.

이 모듈은 그 판단을 눈대중 대신 계산으로 옮긴다. 외부 의존성은 없다.

제공하는 것
  presets  건물 용도별(주거 / 오피스·연구소 / 상업 / 던전·벙커 / 산업) 권장 수치 프리셋
  camera   복도 폭·층고·암 길이로 카메라가 벽에 닿지 않고 돌 수 있는 각도와 필요 후퇴량
  check    한 공간의 복도·문·층고·계단·웅크리기를 한 번에 검사 -> 클리핑 위험도·쾌적도·판정
  stairs   단높이/디딤판으로 Blondel 비·한국 건축법·경사각·단수·계단참·CMC 정합 검사
  clutter  방 면적과 밀도 등급으로 소품 수·종류·인스턴싱 방식·삼각형 예산 추정

사용 예:
    # 용도별 프리셋 목록
    python pipeline/indoor_metric_helper.py presets

    # 오피스·연구소 프리셋에서 복도만 200 cm로 줄였을 때
    python pipeline/indoor_metric_helper.py check --preset office_lab --corridor 200

    # 복도 180 cm, 층고 300 cm, SpringArm 220 cm, 카메라 피치 15도
    python pipeline/indoor_metric_helper.py camera --corridor 180 --ceiling 300 --arm 220 --pitch 15

    # 계단 18/28, 층고 320 cm
    python pipeline/indoor_metric_helper.py stairs --riser 18 --tread 28 --floor-height 320

    # 40 m^2 방, dense 등급, Nanite 사용
    python pipeline/indoor_metric_helper.py clutter --area 40 --grade dense

수치의 근거와 한계는 docs/indoor_exploration_and_spatial_metrics.md 1~3장과 18~20장에 정리했다.
계산은 계획용 근사치다. 최종 값은 metrics zoo 맵에서 실제로 걸어 보고 확정한다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- #
# 상수 (언리얼 엔진 기준)
# --------------------------------------------------------------------------- #

UE_UNITS_PER_METER = 100.0          # 1 uu = 1 cm

# ACharacter / UCharacterMovementComponent 기본값
DEFAULT_CAPSULE_RADIUS = 34.0       # uc.CapsuleRadius
DEFAULT_CAPSULE_HALF_HEIGHT = 88.0  # 176 cm 전고
BASE_EYE_HEIGHT = 64.0              # ACharacter::BaseEyeHeight -> 눈높이 152 cm
DEFAULT_CROUCHED_HALF_HEIGHT = 40.0  # 웅크리기 전고 80 cm (게임에서는 너무 낮다)
DEFAULT_MAX_STEP_HEIGHT = 45.0      # CMC MaxStepHeight
DEFAULT_WALKABLE_FLOOR_ANGLE = 44.765  # CMC WalkableFloorAngle (WalkableFloorZ 0.71)

# USpringArmComponent 기본값
DEFAULT_PROBE_SIZE = 12.0           # 충돌 구체 반경
DEFAULT_ARM_LENGTH = 300.0          # 3인칭 기본 붐 길이
DEFAULT_PITCH_DEG = 15.0            # 아래를 내려다보는 각

# 실제 인체(성인 기준) — 게임 수치와 비교하기 위한 기준값
HUMAN_EYE_HEIGHT = 163.0            # 서 있을 때 눈높이(평균)
HUMAN_SHOULDER_WIDTH = 46.0         # 어깨 폭(양방향)
HUMAN_OCCUPIED_WIDTH = 60.0         # 서 있을 때 점유 폭(팔 포함)
HUMAN_CROUCH_HEIGHT = 120.0         # 실제 웅크린 키

# Blondel 계단 비: 2R + T = 한 걸음(보폭)
BLONDEL_MIN = 60.0
BLONDEL_MAX = 66.0
BLONDEL_IDEAL = 63.0
KOREAN_MAX_RISER = 18.0             # 건축물방화구조규칙 제15조②
KOREAN_MIN_TREAD = 24.0             # 위 규칙의 최소 단너비(주택건설기준은 26)
KOREAN_STAIR_HEADROOM = 210.0       # 계단 유효 높이 2.1 m 이상

# 카메라가 이보다 짧아지면 캐릭터 머리 안으로 들어간 것으로 본다
MIN_USABLE_ARM = 120.0
# 이보다 짧으면 1인칭(또는 숄더 캠)으로 전환하는 편이 낫다
FIRST_PERSON_THRESHOLD = 90.0


class MetricError(ValueError):
    """잘못된 입력. CLI에서는 exit code 1."""


# --------------------------------------------------------------------------- #
# 프리셋
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SpacePreset:
    """건물 용도별 실내 수치 프리셋. 단위는 모두 cm."""

    key: str
    label: str
    corridor_min: float          # 1인 통과 최소
    corridor_standard: float     # 탐사 기본
    corridor_wide: float         # 교행·전투 겸용
    door_width: float            # 싱글 도어
    door_height: float
    double_door_width: float
    ceiling: float               # 마감 천장 높이(바닥~천장)
    floor_to_floor: float        # 층고(바닥~윗층 바닥)
    stair_riser: float
    stair_tread: float
    stair_width: float
    room_module: float           # 기본 방 모듈(그리드)
    camera_arm: float            # 기본 SpringArm 길이
    clutter_grade: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PRESETS: dict[str, SpacePreset] = {
    "residential": SpacePreset(
        key="residential",
        label="주거(폐가·아파트·단독주택)",
        corridor_min=150.0,
        corridor_standard=180.0,
        corridor_wide=240.0,
        door_width=110.0,
        door_height=220.0,
        double_door_width=200.0,
        ceiling=300.0,
        floor_to_floor=320.0,
        stair_riser=18.0,
        stair_tread=28.0,
        stair_width=140.0,
        room_module=400.0,
        camera_arm=220.0,
        clutter_grade="normal",
        note="방이 작아 카메라 후퇴가 잦다. 천장 280 미만은 피한다.",
    ),
    "office_lab": SpacePreset(
        key="office_lab",
        label="오피스·연구소",
        corridor_min=180.0,
        corridor_standard=240.0,
        corridor_wide=320.0,
        door_width=130.0,
        door_height=240.0,
        double_door_width=240.0,
        ceiling=400.0,
        floor_to_floor=430.0,
        stair_riser=17.0,
        stair_tread=29.0,
        stair_width=160.0,
        room_module=400.0,
        camera_arm=260.0,
        clutter_grade="normal",
        note="복도가 길고 개구부가 많다. 문 하나마다 카메라 회전 여유를 남긴다.",
    ),
    "commercial": SpacePreset(
        key="commercial",
        label="상업시설(매장·몰·호텔 로비)",
        corridor_min=240.0,
        corridor_standard=320.0,
        corridor_wide=400.0,
        door_width=150.0,
        door_height=250.0,
        double_door_width=260.0,
        ceiling=450.0,
        floor_to_floor=480.0,
        stair_riser=16.0,
        stair_tread=30.0,
        stair_width=200.0,
        room_module=400.0,
        camera_arm=300.0,
        clutter_grade="dense",
        note="층고가 높아 카메라 피치 여유가 크다. 대신 소품 밀도가 예산을 먹는다.",
    ),
    "dungeon_bunker": SpacePreset(
        key="dungeon_bunker",
        label="던전·벙커(지하 시설)",
        corridor_min=180.0,
        corridor_standard=220.0,
        corridor_wide=300.0,
        door_width=120.0,
        door_height=230.0,
        double_door_width=220.0,
        ceiling=350.0,
        floor_to_floor=400.0,
        stair_riser=18.0,
        stair_tread=28.0,
        stair_width=150.0,
        room_module=400.0,
        camera_arm=240.0,
        clutter_grade="sparse",
        note="조명이 적어 시야가 짧다. 통로는 넓히고 소품은 줄인다.",
    ),
    "industrial": SpacePreset(
        key="industrial",
        label="산업시설(창고·발전소·대형 홀)",
        corridor_min=250.0,
        corridor_standard=350.0,
        corridor_wide=500.0,
        door_width=200.0,
        door_height=280.0,
        double_door_width=300.0,
        ceiling=600.0,
        floor_to_floor=650.0,
        stair_riser=18.0,
        stair_tread=28.0,
        stair_width=240.0,
        room_module=800.0,
        camera_arm=350.0,
        clutter_grade="sparse",
        note="통로 폭은 넉넉하지만 시야가 길어 라이트 수와 오클루전이 문제가 된다.",
    ),
}

DEFAULT_PRESET = "residential"

CLUTTER_GRADES: dict[str, dict[str, float]] = {
    # 1 m^2 당 소품 수 / 25 m^2 당 소품 종류 / 소품 평균 삼각형
    "sparse": {"per_m2": 0.20, "variants_per_25m2": 4.0, "avg_tris": 12000.0},
    "normal": {"per_m2": 0.45, "variants_per_25m2": 7.0, "avg_tris": 18000.0},
    "dense": {"per_m2": 0.80, "variants_per_25m2": 10.0, "avg_tris": 25000.0},
    "cluttered": {"per_m2": 1.25, "variants_per_25m2": 14.0, "avg_tris": 35000.0},
}


# --------------------------------------------------------------------------- #
# 카메라 붐 기하
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CameraClearance:
    """복도 폭과 층고가 허락하는 SpringArm 길이·회전각."""

    corridor_width: float
    ceiling_height: float
    arm_length: float
    probe_size: float
    pitch_deg: float
    shoulder_offset: float
    eye_height: float
    lateral_budget: float        # 카메라 중심이 벽에 닿기까지 쓸 수 있는 좌우 거리
    lateral_reach: float         # 현재 암이 수평으로 뻗는 거리
    vertical_budget: float       # 천장까지 남은 높이
    free_yaw_deg: float          # 암을 온전히 유지한 채 돌 수 있는 최대 좌우 각
    free_pitch_deg: float        # 암을 온전히 유지한 채 올려다볼 수 있는 최대 각
    allowed_arm_lateral: float   # 정면(yaw 90도)에서 허용되는 최대 암
    allowed_arm_vertical: float  # 천장에 닿지 않는 최대 암
    allowed_arm: float           # 위 둘과 설정값 중 최솟값
    retract_ratio: float         # 0 = 전혀 안 줄어듦, 1 = 완전히 접힘
    mode: str                    # full_orbit / retract / short_arm / first_person
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def camera_clearance(
    corridor_width: float,
    ceiling_height: float,
    arm_length: float = DEFAULT_ARM_LENGTH,
    probe_size: float = DEFAULT_PROBE_SIZE,
    pitch_deg: float = DEFAULT_PITCH_DEG,
    shoulder_offset: float = 0.0,
    eye_height: float = DEFAULT_CAPSULE_HALF_HEIGHT + BASE_EYE_HEIGHT,
) -> CameraClearance:
    """복도 폭·층고 안에서 SpringArm이 실제로 쓸 수 있는 길이와 회전각.

    모델:
      - 카메라 피벗은 눈높이(기본 152 cm)에 있고, 숄더 오프셋만큼 좌우로 밀려 있다.
      - SpringArm은 피치각 phi로 기울어 길이 L만큼 뻗는다.
        수평 성분 L*cos(phi), 수직 성분 L*sin(phi).
      - 복도 축 기준 요(yaw) theta로 돌면 카메라의 좌우 이동량은
        shoulder + L*cos(phi)*sin(theta)이고, 이는 (복도폭/2 - probe)를 넘을 수 없다.
      - theta = 90도(벽을 정면으로 보는 상태)에서 허용 암 길이가 가장 짧아진다.
    """
    if corridor_width <= 0 or ceiling_height <= 0:
        raise MetricError("복도 폭과 층고는 0보다 커야 합니다.")
    if arm_length <= 0:
        raise MetricError("암 길이는 0보다 커야 합니다.")
    if probe_size <= 0:
        raise MetricError("probe 크기는 0보다 커야 합니다.")

    pitch = math.radians(_clamp(pitch_deg, -80.0, 80.0))
    cos_p = max(math.cos(pitch), 1e-6)
    sin_p = math.sin(pitch)

    lateral_budget = max(corridor_width / 2.0 - probe_size - shoulder_offset, 0.0)
    lateral_reach = arm_length * cos_p
    vertical_budget_up = max(ceiling_height - eye_height - probe_size, 0.0)
    vertical_budget_down = max(eye_height - probe_size, 0.0)

    # 정면(yaw 90도)에서 좌우로 뻗을 수 있는 최대 암
    allowed_arm_lateral = lateral_budget / cos_p
    # 위를 볼 때(pitch>0이면 카메라가 피벗 위로 올라간다) 천장에 닿지 않는 최대 암
    if sin_p > 1e-6:
        allowed_arm_vertical = vertical_budget_up / sin_p
    elif sin_p < -1e-6:
        allowed_arm_vertical = vertical_budget_down / abs(sin_p)
    else:
        allowed_arm_vertical = float("inf")

    allowed_arm = min(arm_length, allowed_arm_lateral, allowed_arm_vertical)
    retract_ratio = _clamp(1.0 - allowed_arm / arm_length, 0.0, 1.0)

    if lateral_reach > 1e-6:
        free_yaw = math.degrees(math.asin(_clamp(lateral_budget / lateral_reach, 0.0, 1.0)))
    else:
        free_yaw = 90.0

    if arm_length > 1e-6:
        free_pitch = math.degrees(math.asin(_clamp(vertical_budget_up / arm_length, 0.0, 1.0)))
    else:
        free_pitch = 0.0

    if allowed_arm < FIRST_PERSON_THRESHOLD:
        mode = "first_person"
    elif allowed_arm < MIN_USABLE_ARM:
        mode = "short_arm"
    elif retract_ratio > 0.02:
        mode = "retract"
    else:
        mode = "full_orbit"

    warnings: list[str] = []
    if free_yaw < 25.0:
        warnings.append(
            f"좌우 회전 여유가 {free_yaw:.1f}도뿐입니다. 복도를 따라 걸을 때도 카메라가 벽에 붙습니다."
        )
    if allowed_arm < MIN_USABLE_ARM:
        warnings.append(
            f"벽을 정면으로 보면 암이 {allowed_arm:.0f} cm까지 접힙니다. 캐릭터가 화면을 덮습니다."
        )
    if pitch_deg >= 0 and vertical_budget_up < 2 * probe_size:
        warnings.append("천장 여유가 probe 지름보다 작습니다. 위를 볼 때 카메라가 천장을 뚫습니다.")
    if pitch_deg < 0 and vertical_budget_down < 2 * probe_size:
        warnings.append("바닥 여유가 probe 지름보다 작습니다. 아래를 볼 때 카메라가 바닥을 뚫습니다.")
    if shoulder_offset >= lateral_budget:
        warnings.append("숄더 오프셋이 좌우 여유를 모두 먹었습니다. SocketOffset 대신 암 회전을 쓴다.")

    return CameraClearance(
        corridor_width=round(corridor_width, 2),
        ceiling_height=round(ceiling_height, 2),
        arm_length=round(arm_length, 2),
        probe_size=round(probe_size, 2),
        pitch_deg=round(pitch_deg, 3),
        shoulder_offset=round(shoulder_offset, 2),
        eye_height=round(eye_height, 2),
        lateral_budget=round(lateral_budget, 2),
        lateral_reach=round(lateral_reach, 2),
        vertical_budget=round(vertical_budget_up, 2),
        free_yaw_deg=round(free_yaw, 2),
        free_pitch_deg=round(free_pitch, 2),
        allowed_arm_lateral=round(min(allowed_arm_lateral, 9999.0), 2),
        allowed_arm_vertical=round(min(allowed_arm_vertical, 9999.0), 2),
        allowed_arm=round(allowed_arm, 2),
        retract_ratio=round(retract_ratio, 4),
        mode=mode,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------- #
# 공간 검사
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    value: float
    unit: str
    status: str          # pass / warn / fail
    detail: str
    blocking: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpaceReport:
    """한 공간(복도·문·층고·계단)의 검사 결과와 점수."""

    preset: str
    corridor_width: float
    door_width: float
    door_height: float
    ceiling_height: float
    capsule_radius: float
    capsule_height: float
    eye_height: float
    crouch_height: float
    camera: CameraClearance
    clipping_risk: float     # 0(안전) ~ 100(항상 벽에 붙음)
    comfort: float           # 0 ~ 100
    verdict: str
    checks: tuple[CheckResult, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["camera"] = self.camera.as_dict()
        data["checks"] = [c.as_dict() for c in self.checks]
        return data

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.status == "fail")

    @property
    def warnings(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.status == "warn")


def _status_from(value: float, warn_at: float, pass_at: float) -> str:
    """값이 클수록 좋은 지표. pass_at 이상이면 pass, warn_at 미만이면 fail."""
    if value >= pass_at:
        return "pass"
    if value >= warn_at:
        return "warn"
    return "fail"


def check_stairs(
    riser: float,
    tread: float,
    floor_height: float | None = None,
    width: float | None = None,
    headroom: float | None = None,
) -> "StairReport":
    """단높이·디딤판으로 계단의 걸음 편안함과 법규 정합을 검사한다."""
    if riser <= 0 or tread <= 0:
        raise MetricError("단높이와 디딤판은 0보다 커야 합니다.")

    ratio = 2.0 * riser + tread
    angle = math.degrees(math.atan2(riser, tread))

    checks: list[CheckResult] = []

    if BLONDEL_MIN <= ratio <= BLONDEL_MAX:
        blondel = "pass"
        blondel_detail = (
            f"2R+T = {ratio:.0f} cm — Blondel 보폭 범위({BLONDEL_MIN:.0f}~{BLONDEL_MAX:.0f}) 안, "
            f"이상값 {BLONDEL_IDEAL:.0f}"
        )
    elif 57.0 <= ratio < BLONDEL_MIN or BLONDEL_MAX < ratio <= 69.0:
        blondel = "warn"
        blondel_detail = f"2R+T = {ratio:.0f} cm — 범위 밖. 한 단씩 오를 때 리듬이 어긋난다"
    else:
        blondel = "fail"
        blondel_detail = f"2R+T = {ratio:.0f} cm — 계단이 아니라 턱이나 비탈에 가깝다"
    checks.append(CheckResult("stair.blondel", "Blondel 보폭 비", round(ratio, 1), "cm", blondel, blondel_detail))

    code_ok = riser <= KOREAN_MAX_RISER and tread >= KOREAN_MIN_TREAD
    checks.append(CheckResult(
        "stair.code", "한국 건축법(단높이 18 / 단너비 24 이하·이상)",
        riser, "cm",
        "pass" if code_ok else "fail",
        f"단높이 {riser:.0f} cm(≤18), 단너비 {tread:.0f} cm(≥24) — "
        + ("법규 하한을 만족" if code_ok else "법규 하한 위반. 게임에서도 계단이 급해 보인다"),
    ))

    slope_status = "pass" if 26.0 <= angle <= 36.0 else ("warn" if 20.0 <= angle <= 40.0 else "fail")
    checks.append(CheckResult(
        "stair.slope", "계단 경사각", round(angle, 1), "deg", slope_status,
        f"{angle:.1f}도 — 이상 26~36도. 40도를 넘으면 오르내릴 때 캐릭터가 미끄러지는 느낌이 난다",
    ))

    cmc_ok = angle <= DEFAULT_WALKABLE_FLOOR_ANGLE
    checks.append(CheckResult(
        "stair.cmc", "경사 콜리전 사용 가능 여부(CMC 44.765도)",
        round(angle, 1), "deg",
        "pass" if cmc_ok else "fail",
        "계단을 하나의 경사면 콜리전으로 대체해도 캐릭터가 걸어 오를 수 있다"
        if cmc_ok else
        f"{angle:.1f}도 > {DEFAULT_WALKABLE_FLOOR_ANGLE:.3f}도 — 경사 콜리전으로는 못 오른다. 단별 콜리전 필요",
    ))

    if riser > DEFAULT_MAX_STEP_HEIGHT:
        checks.append(CheckResult(
            "stair.step", "MaxStepHeight(45 cm) 초과", riser, "cm", "fail",
            "한 단이 45 cm를 넘으면 자동 단 오르기(StepUp)가 실패한다",
        ))

    steps = None
    run = None
    landings = None
    if floor_height is not None:
        if floor_height <= 0:
            raise MetricError("층고는 0보다 커야 합니다.")
        steps = max(1, math.ceil(floor_height / riser))
        actual_riser = floor_height / steps
        run = steps * tread
        # 건축물방화구조규칙: 높이 3 m를 넘는 계단에는 3 m 이내마다 계단참
        landings = 0 if floor_height <= 300.0 else math.ceil(floor_height / 300.0) - 1
        checks.append(CheckResult(
            "stair.count", "단수와 실제 단높이", float(steps), "단",
            "pass",
            f"층고 {floor_height:.0f} cm -> {steps}단, 실제 단높이 {actual_riser:.1f} cm, "
            f"수평 투영 길이 {run:.0f} cm",
        ))
        if landings:
            checks.append(CheckResult(
                "stair.landing", "계단참 필요 개수", float(landings), "개", "warn",
                f"3 m 초과 계단 — 3 m 이내마다 유효너비 120 cm 이상 계단참이 필요하다(법규). "
                f"깊이는 140 cm 이상 권장",
            ))

    if headroom is not None:
        checks.append(CheckResult(
            "stair.headroom", "계단 유효 높이", headroom, "cm",
            "pass" if headroom >= KOREAN_STAIR_HEADROOM else "fail",
            f"{headroom:.0f} cm — 법규 최소 {KOREAN_STAIR_HEADROOM:.0f} cm. "
            "3인칭 카메라는 여기에 암 길이의 수직 성분이 더 필요하다",
        ))

    if width is not None:
        checks.append(CheckResult(
            "stair.width", "계단 유효너비", width, "cm",
            "pass" if width >= 140.0 else ("warn" if width >= 120.0 else "fail"),
            f"{width:.0f} cm — 법규 최소 120 cm, 2인 교행과 카메라는 140 cm 이상을 요구한다",
        ))

    score = 100.0
    for c in checks:
        if c.status == "warn":
            score -= 8.0
        elif c.status == "fail":
            score -= 25.0
    score = _clamp(score, 0.0, 100.0)

    return StairReport(
        riser=riser,
        tread=tread,
        ratio=round(ratio, 2),
        angle_deg=round(angle, 2),
        floor_height=floor_height,
        steps=steps,
        run_cm=None if run is None else round(run, 1),
        landings=landings,
        score=round(score, 1),
        checks=tuple(checks),
    )


@dataclass(frozen=True)
class StairReport:
    riser: float
    tread: float
    ratio: float
    angle_deg: float
    floor_height: float | None
    steps: int | None
    run_cm: float | None
    landings: int | None
    score: float
    checks: tuple[CheckResult, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = [c.as_dict() for c in self.checks]
        return data


def spacing_compliance(value: float, minimum: float) -> float:
    """비율 기반 쾌적도(0~1). 기준값의 1.6배에서 1.0이 된다."""
    if minimum <= 0:
        raise MetricError("기준값은 0보다 커야 합니다.")
    return _clamp((value - minimum) / (minimum * 0.6), 0.0, 1.0)


def analyze_space(
    corridor_width: float,
    door_width: float,
    door_height: float,
    ceiling_height: float,
    preset: str = DEFAULT_PRESET,
    arm_length: float | None = None,
    probe_size: float = DEFAULT_PROBE_SIZE,
    pitch_deg: float = DEFAULT_PITCH_DEG,
    shoulder_offset: float = 0.0,
    capsule_radius: float = DEFAULT_CAPSULE_RADIUS,
    capsule_height: float = DEFAULT_CAPSULE_HALF_HEIGHT * 2.0,
    eye_height: float | None = None,
    crouch_height: float = 105.0,
    stair_riser: float | None = None,
    stair_tread: float | None = None,
) -> SpaceReport:
    """한 공간의 실내 수치를 검사하고 클리핑 위험도·쾌적도를 낸다."""
    for name, value in (
        ("복도 폭", corridor_width),
        ("문 폭", door_width),
        ("문 높이", door_height),
        ("층고", ceiling_height),
    ):
        if value <= 0:
            raise MetricError(f"{name}은 0보다 커야 합니다.")
    if capsule_radius <= 0 or capsule_height <= 0:
        raise MetricError("캡슐 치수는 0보다 커야 합니다.")

    # ACharacter::BaseEyeHeight는 캡슐 중심에서 위로 잰 값이다 -> 눈높이 = 반높이 + 64
    eye = capsule_height / 2.0 + BASE_EYE_HEIGHT if eye_height is None else eye_height
    if arm_length is None:
        arm_length = PRESETS.get(preset, PRESETS[DEFAULT_PRESET]).camera_arm

    camera = camera_clearance(
        corridor_width=corridor_width,
        ceiling_height=ceiling_height,
        arm_length=arm_length,
        probe_size=probe_size,
        pitch_deg=pitch_deg,
        shoulder_offset=shoulder_offset,
        eye_height=eye,
    )

    checks: list[CheckResult] = []
    capsule_diameter = capsule_radius * 2.0

    # 1. 복도: 지나갈 수 있는가
    corridor_status = _status_from(corridor_width, capsule_diameter + 20.0, 150.0)
    checks.append(CheckResult(
        "corridor.passable", "복도 1인 통과", corridor_width, "cm", corridor_status,
        f"폭 {corridor_width:.0f} cm, 캡슐 지름 {capsule_diameter:.0f} cm(어깨 {HUMAN_SHOULDER_WIDTH:.0f} cm보다 "
        f"{capsule_diameter - HUMAN_SHOULDER_WIDTH:.0f} cm 큼) -> "
        f"좌우 여유 {(corridor_width - capsule_diameter) / 2.0:.0f} cm. "
        "탐사 기준 150 cm 미만이면 벽이 시야를 계속 때린다",
        blocking=(corridor_status == "fail"),
    ))

    # 2. 복도: 두 캐릭터가 지나갈 수 있는가
    passing_need = HUMAN_OCCUPIED_WIDTH * 2.0 + 60.0  # 180 cm
    checks.append(CheckResult(
        "corridor.passing", "2인 교행", corridor_width, "cm",
        _status_from(corridor_width, passing_need - 20.0, 200.0),
        f"두 캐릭터({HUMAN_OCCUPIED_WIDTH:.0f} cm) + 사이 여유 60 cm = {passing_need:.0f} cm 필요. "
        "NPC가 지나다니는 공간이면 200 cm 이상",
    ))

    # 3. 복도: 벽에 붙일 소품 여유
    side_margin = (corridor_width - HUMAN_OCCUPIED_WIDTH * 2.0) / 2.0
    checks.append(CheckResult(
        "corridor.props", "복도 소품 여유", side_margin, "cm",
        _status_from(side_margin, 10.0, 45.0),
        f"양옆 각 {side_margin:.0f} cm — 25 cm 미만이면 액자·배관·문손잡이가 통행을 방해한다",
    ))

    # 4. 복도: 카메라 회전 여유
    checks.append(CheckResult(
        "corridor.camera", "카메라 좌우 회전 여유", camera.free_yaw_deg, "deg",
        _status_from(camera.free_yaw_deg, 25.0, 45.0),
        f"암 {arm_length:.0f} cm로 좌우 {camera.free_yaw_deg:.0f}도까지 벽에 닿지 않는다 "
        f"(필요 각 45도)",
    ))

    # 5. 문: 통과 여유
    door_margin = door_width - capsule_diameter
    door_status = "pass" if door_margin >= 40.0 else ("warn" if door_margin >= 25.0 else "fail")
    checks.append(CheckResult(
        "door.clearance", "문 통과 여유", door_margin, "cm", door_status,
        f"문 {door_width:.0f} cm - 캡슐 {capsule_diameter:.0f} cm = {door_margin:.0f} cm. "
        "25 cm 미만이면 달리며 들어갈 때 문틀에 걸린다",
        blocking=(door_status == "fail"),
    ))

    # 6. 문: 머리 위 여유(상인방)
    door_headroom = door_height - capsule_height
    checks.append(CheckResult(
        "door.headroom", "문 상인방 여유", door_headroom, "cm",
        "pass" if door_headroom >= 40.0 else ("warn" if door_headroom >= 20.0 else "fail"),
        f"문 높이 {door_height:.0f} cm - 캐릭터 {capsule_height:.0f} cm = {door_headroom:.0f} cm. "
        "20 cm 미만이면 점프·계단 위에서 문턱에 머리가 걸린다",
    ))

    # 7. 천장 높이
    checks.append(CheckResult(
        "ceiling.height", "천장 높이", ceiling_height, "cm",
        "pass" if ceiling_height >= 260.0 else ("warn" if ceiling_height >= 230.0 else "fail"),
        f"{ceiling_height:.0f} cm — 주거 280~320, 오피스 360~450 권장. 성인 눈높이"
        f"({HUMAN_EYE_HEIGHT:.0f} cm) 기준 머리 위 여유 {ceiling_height - HUMAN_EYE_HEIGHT:.0f} cm. "
        "230 cm 미만은 실제 건축에서도 창고·지하 통로 수준",
    ))

    # 8. 천장: 카메라 피치 여유
    checks.append(CheckResult(
        "ceiling.camera", "카메라 상향 여유", camera.free_pitch_deg, "deg",
        _status_from(camera.free_pitch_deg, 15.0, 25.0),
        f"암을 줄이지 않고 {camera.free_pitch_deg:.0f}도까지 올려다볼 수 있다. "
        "계단을 오르며 위를 볼 때 필요",
    ))

    # 9. 웅크리기
    checks.append(CheckResult(
        "crouch.fit", "웅크리기 높이", crouch_height, "cm",
        "pass" if crouch_height >= 100.0 else ("warn" if crouch_height >= 90.0 else "fail"),
        f"{crouch_height:.0f} cm — UE 기본 CrouchedHalfHeight "
        f"{DEFAULT_CROUCHED_HALF_HEIGHT:.0f}({DEFAULT_CROUCHED_HALF_HEIGHT * 2:.0f} cm)은 실제 웅크림"
        f"({HUMAN_CROUCH_HEIGHT:.0f} cm)보다 낮아 기어가는 느낌이 난다. 100~110 권장",
        blocking=(crouch_height < 80.0),
    ))

    # 10. 계단(선택)
    if stair_riser is not None and stair_tread is not None:
        stair = check_stairs(stair_riser, stair_tread)
        for c in stair.checks:
            if c.key in ("stair.blondel", "stair.code", "stair.slope"):
                checks.append(c)

    # 점수 ------------------------------------------------------------------
    body_score = spacing_compliance(corridor_width - capsule_diameter, 40.0)
    door_score = spacing_compliance(door_margin, 25.0)
    head_score = spacing_compliance(ceiling_height - capsule_height, 80.0)
    camera_score = _clamp(camera.free_yaw_deg / 45.0, 0.0, 1.0)
    crouch_score = _clamp((crouch_height - 80.0) / 30.0, 0.0, 1.0)

    weights = {
        "body": 0.22,
        "door": 0.16,
        "head": 0.17,
        "camera": 0.33,
        "crouch": 0.12,
    }
    parts = {
        "body": body_score,
        "door": door_score,
        "head": head_score,
        "camera": camera_score,
        "crouch": crouch_score,
    }
    comfort = sum(parts[k] * weights[k] for k in weights) / sum(weights.values()) * 100.0
    comfort = round(_clamp(comfort, 0.0, 100.0), 1)

    risk_lateral = _clamp(1.0 - camera.lateral_budget / camera.lateral_reach, 0.0, 1.0) \
        if camera.lateral_reach > 1e-6 else 1.0
    risk_vertical = _clamp(
        1.0 - camera.vertical_budget / (arm_length * max(math.sin(math.radians(pitch_deg)), 1e-6)),
        0.0, 1.0,
    ) if pitch_deg > 0 else 0.0
    risk_door = _clamp(1.0 - door_margin / 40.0, 0.0, 1.0)
    clipping_risk = round(max(risk_lateral, risk_vertical, risk_door * 0.8) * 100.0, 1)

    has_fail = any(c.status == "fail" for c in checks)
    if any(c.blocking and c.status == "fail" for c in checks):
        verdict = "탐사 불가"
    elif comfort >= 80.0 and not has_fail:
        verdict = "권장"
    elif comfort >= 65.0 and not has_fail:
        verdict = "양호"
    elif comfort >= 50.0:
        verdict = "주의"
    else:
        verdict = "위험"

    return SpaceReport(
        preset=preset,
        corridor_width=round(corridor_width, 2),
        door_width=round(door_width, 2),
        door_height=round(door_height, 2),
        ceiling_height=round(ceiling_height, 2),
        capsule_radius=round(capsule_radius, 2),
        capsule_height=round(capsule_height, 2),
        eye_height=round(eye, 2),
        crouch_height=round(crouch_height, 2),
        camera=camera,
        clipping_risk=clipping_risk,
        comfort=comfort,
        verdict=verdict,
        checks=tuple(checks),
    )


# --------------------------------------------------------------------------- #
# 소품 밀도 예산
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ClutterBudget:
    area_m2: float
    grade: str
    nanite: bool
    props: int
    variants: int
    instances_per_variant: float
    component: str
    avg_tris: float
    triangles: int
    draw_estimate: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def clutter_budget(
    area_m2: float,
    grade: str = "normal",
    nanite: bool = True,
    materials_per_prop: float = 1.5,
) -> ClutterBudget:
    """방 면적과 밀도 등급으로 소품 수·종류·인스턴싱 방식·삼각형 예산을 추정한다.

    - 밀도 등급은 "장식물 수"가 아니라 "시선이 걸리는 오브젝트 수"다. 사람이 방에
      들어섰을 때 한 번에 읽히는 오브젝트는 7~12개 수준이고, 그 이상은 그룹으로 뭉친다.
    - Nanite 프로젝트에서는 ISM이 기본이다(Epic 권장: HISM은 비-Nanite 플랫폼용).
    """
    if area_m2 <= 0:
        raise MetricError("방 면적은 0보다 커야 합니다.")
    if grade not in CLUTTER_GRADES:
        raise MetricError(
            f"알 수 없는 밀도 등급: {grade!r} (가능: {', '.join(sorted(CLUTTER_GRADES))})"
        )
    data = CLUTTER_GRADES[grade]
    props = max(1, round(area_m2 * data["per_m2"]))
    variants = max(1, round(area_m2 / 25.0 * data["variants_per_25m2"]))
    if variants > props:
        variants = props
    instances = props / variants
    triangles = int(round(props * data["avg_tris"]))
    component = "ISM" if nanite else "HISM"
    draw_estimate = int(round(variants * materials_per_prop))

    warnings: list[str] = []
    if grade == "cluttered" and area_m2 < 20.0:
        warnings.append("20 m^2 미만에 cluttered 등급은 통행 폭을 먹는다. 복도 폭을 먼저 확인한다.")
    if variants > 40:
        warnings.append(
            f"소품 종류 {variants}개 — 방 하나에서 이만큼 다른 메시를 쓰면 '프리팹 티'가 나고 "
            "메모리·드로우 예산도 흔들린다. 25~35종으로 묶고 스케일·회전·색으로 변주한다."
        )
    if not nanite and props > 200:
        warnings.append(f"비-Nanite에서 {props}개 인스턴스는 HISM 클러스터 빌드 비용이 크다. 청크로 나눈다.")
    if triangles > 1_200_000:
        warnings.append(
            f"소품 삼각형 {triangles:,}개 — 방 하나 기준 1.2M을 넘었다. 화면에 방이 둘 보이면 예산 초과."
        )
    if instances < 1.5 and props > 8:
        warnings.append("종류 대비 개체 수가 1.5 미만 — 같은 메시를 여러 번 놓아 변주를 만든다.")

    return ClutterBudget(
        area_m2=round(area_m2, 2),
        grade=grade,
        nanite=nanite,
        props=props,
        variants=variants,
        instances_per_variant=round(instances, 2),
        component=component,
        avg_tris=data["avg_tris"],
        triangles=triangles,
        draw_estimate=draw_estimate,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------- #
# 프리셋 해석
# --------------------------------------------------------------------------- #

def get_preset(key: str) -> SpacePreset:
    if key not in PRESETS:
        raise MetricError(f"알 수 없는 프리셋: {key!r} (가능: {', '.join(sorted(PRESETS))})")
    return PRESETS[key]


def resolve_spec(
    preset_key: str = DEFAULT_PRESET,
    overrides: Mapping[str, float | None] | None = None,
) -> dict[str, float]:
    """프리셋 값에 사용자 입력을 덮어써 최종 수치를 만든다."""
    preset = get_preset(preset_key)
    spec: dict[str, float] = {
        "corridor_width": preset.corridor_standard,
        "door_width": preset.door_width,
        "door_height": preset.door_height,
        "ceiling_height": preset.ceiling,
        "arm_length": preset.camera_arm,
        "stair_riser": preset.stair_riser,
        "stair_tread": preset.stair_tread,
    }
    for key, value in (overrides or {}).items():
        if value is not None:
            spec[key] = float(value)
    return spec


# --------------------------------------------------------------------------- #
# 텍스트 출력
# --------------------------------------------------------------------------- #

_STATUS_MARK = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}


def format_presets() -> str:
    lines = []
    for key in PRESETS:
        p = PRESETS[key]
        lines.append(
            f"{p.key:<15} {p.label}\n"
            f"{'':<15} 복도 {p.corridor_min:.0f}/{p.corridor_standard:.0f}/{p.corridor_wide:.0f} cm · "
            f"문 {p.door_width:.0f}x{p.door_height:.0f} cm · 천장 {p.ceiling:.0f} cm · "
            f"층고 {p.floor_to_floor:.0f} cm · 암 {p.camera_arm:.0f} cm · 소품 {p.clutter_grade}"
        )
    return "\n".join(lines)


def format_preset(preset: SpacePreset) -> str:
    lines = [
        f"{preset.label}  ({preset.key})",
        f"  복도          최소 {preset.corridor_min:.0f} / 기본 {preset.corridor_standard:.0f} / "
        f"교행 {preset.corridor_wide:.0f} cm",
        f"  문            싱글 {preset.door_width:.0f} x {preset.door_height:.0f} cm, "
        f"더블 {preset.double_door_width:.0f} cm",
        f"  천장/층고     {preset.ceiling:.0f} / {preset.floor_to_floor:.0f} cm",
        f"  계단          {preset.stair_riser:.0f} / {preset.stair_tread:.0f} cm, "
        f"폭 {preset.stair_width:.0f} cm",
        f"  방 모듈       {preset.room_module:.0f} cm 그리드",
        f"  카메라 암     {preset.camera_arm:.0f} cm",
        f"  소품 밀도     {preset.clutter_grade}",
        f"  메모          {preset.note}",
    ]
    return "\n".join(lines)


def format_camera(cam: CameraClearance) -> str:
    lines = [
        f"복도 {cam.corridor_width:.0f} cm | 천장 {cam.ceiling_height:.0f} cm | "
        f"암 {cam.arm_length:.0f} cm | 피치 {cam.pitch_deg:.0f}도 | probe {cam.probe_size:.0f} cm",
        f"  좌우 여유         {cam.lateral_budget:.0f} cm  "
        f"(카메라 중심이 벽에서 {cam.probe_size:.0f} cm 이상 떨어져야 한다)",
        f"  천장 여유         {cam.vertical_budget:.0f} cm",
        f"  좌우 회전 한계     +-{cam.free_yaw_deg:.1f}도  (45도 이상이면 편안)",
        f"  상향 회전 한계     {cam.free_pitch_deg:.1f}도  (25도 이상이면 편안)",
        f"  벽 정면 시 허용 암 {cam.allowed_arm_lateral:.0f} cm",
        f"  허용 암 길이       {cam.allowed_arm:.0f} cm  (후퇴율 {cam.retract_ratio * 100:.0f}%)",
        f"  모드              {cam.mode}",
    ]
    lines += [f"  [경고] {w}" for w in cam.warnings]
    return "\n".join(lines)


def format_space(report: SpaceReport) -> str:
    lines = [
        f"{report.verdict}  |  쾌적도 {report.comfort:.1f} / 100  "
        f"|  클리핑 위험도 {report.clipping_risk:.1f} / 100  ({report.preset})",
        "  (위험도는 카메라를 벽 쪽으로 완전히 돌렸을 때 기준 — 낮을수록 여유가 크다)",
        f"  복도 {report.corridor_width:.0f} cm | 문 {report.door_width:.0f}x{report.door_height:.0f} cm "
        f"| 천장 {report.ceiling_height:.0f} cm | 암 {report.camera.arm_length:.0f} cm",
        f"  카메라: 좌우 +-{report.camera.free_yaw_deg:.1f}도, 상향 {report.camera.free_pitch_deg:.1f}도, "
        f"허용 암 {report.camera.allowed_arm:.0f} cm ({report.camera.mode})",
        "",
    ]
    for c in report.checks:
        mark = _STATUS_MARK[c.status]
        value = f"{c.value:g} {c.unit}" if c.unit else f"{c.value:g}"
        lines.append(f"  [{mark}] {c.label:<28} {value:>10}  {c.detail}")
    if report.failures:
        lines.append("")
        lines.append("고쳐야 할 것: " + ", ".join(c.key for c in report.failures))
    if report.warnings:
        lines.append("조정 권장: " + ", ".join(c.key for c in report.warnings))
    return "\n".join(lines)


def format_stairs(report: StairReport) -> str:
    head = f"계단 {report.riser:.0f}/{report.tread:.0f} cm  |  2R+T {report.ratio:.0f} cm  " \
           f"|  경사 {report.angle_deg:.1f}도  |  점수 {report.score:.1f}"
    lines = [head]
    if report.floor_height is not None:
        lines.append(
            f"  층고 {report.floor_height:.0f} cm -> {report.steps}단, "
            f"수평 길이 {report.run_cm:.0f} cm"
            + (f", 계단참 {report.landings}개 필요" if report.landings else "")
        )
    for c in report.checks:
        mark = _STATUS_MARK[c.status]
        value = f"{c.value:g} {c.unit}" if c.unit else f"{c.value:g}"
        lines.append(f"  [{mark}] {c.label:<34} {value:>10}  {c.detail}")
    return "\n".join(lines)


def format_clutter(budget: ClutterBudget) -> str:
    lines = [
        f"{budget.area_m2:.0f} m^2 · {budget.grade} · {'Nanite' if budget.nanite else 'Non-Nanite'}",
        f"  소품 개체        {budget.props}개",
        f"  소품 종류        {budget.variants}종 (종류당 {budget.instances_per_variant:.1f}개)",
        f"  컴포넌트         {budget.component}",
        f"  삼각형 추정      {budget.triangles:,} (평균 {budget.avg_tris:,.0f})",
        f"  드로우 추정      {budget.draw_estimate} (종류 x 머티리얼)",
    ]
    lines += [f"  [경고] {w}" for w in budget.warnings]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="텍스트 대신 JSON으로 출력")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="indoor_metric_helper",
        description="인게임 실내 탐사 공간 수치 계산기 (복도·문·층고·계단·카메라 붐·소품 밀도)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    presets = sub.add_parser("presets", help="용도별 프리셋 목록")
    _add_common(presets)

    preset = sub.add_parser("preset", help="프리셋 하나의 전체 수치")
    preset.add_argument("--type", default=DEFAULT_PRESET, choices=sorted(PRESETS))
    _add_common(preset)

    cam = sub.add_parser("camera", help="복도 폭·층고에서 카메라가 쓸 수 있는 길이와 각도")
    cam.add_argument("--corridor", type=float, required=True, help="복도 폭(cm)")
    cam.add_argument("--ceiling", type=float, required=True, help="천장 높이(cm)")
    cam.add_argument("--arm", type=float, default=DEFAULT_ARM_LENGTH, help="SpringArm 길이(cm)")
    cam.add_argument("--probe", type=float, default=DEFAULT_PROBE_SIZE, help="ProbeSize(cm)")
    cam.add_argument("--pitch", type=float, default=DEFAULT_PITCH_DEG, help="카메라 피치(도)")
    cam.add_argument("--shoulder", type=float, default=0.0, help="좌우 오프셋(cm)")
    cam.add_argument("--eye", type=float, default=DEFAULT_CAPSULE_HALF_HEIGHT + BASE_EYE_HEIGHT,
                     help="눈높이(cm)")
    _add_common(cam)

    check = sub.add_parser("check", help="복도·문·층고·웅크리기·계단 종합 검사")
    check.add_argument("--preset", default=DEFAULT_PRESET, choices=sorted(PRESETS))
    check.add_argument("--corridor", type=float, help="복도 폭(cm). 미지정 시 프리셋 기본값")
    check.add_argument("--door", type=float, help="문 폭(cm)")
    check.add_argument("--door-height", type=float, help="문 높이(cm)")
    check.add_argument("--ceiling", type=float, help="천장 높이(cm)")
    check.add_argument("--arm", type=float, help="SpringArm 길이(cm)")
    check.add_argument("--probe", type=float, default=DEFAULT_PROBE_SIZE)
    check.add_argument("--pitch", type=float, default=DEFAULT_PITCH_DEG)
    check.add_argument("--shoulder", type=float, default=0.0, help="좌우 오프셋(cm)")
    check.add_argument("--capsule-radius", type=float, default=DEFAULT_CAPSULE_RADIUS)
    check.add_argument("--capsule-height", type=float, default=DEFAULT_CAPSULE_HALF_HEIGHT * 2.0)
    check.add_argument("--eye", type=float, help="눈높이(cm). 기본은 캡슐 높이 - 64")
    check.add_argument("--crouch", type=float, default=105.0,
                       help="웅크리기 전고(cm). UE 기본은 80이지만 권장은 100~110")
    check.add_argument("--stair-riser", type=float, help="단높이(cm)")
    check.add_argument("--stair-tread", type=float, help="디딤판(cm)")
    _add_common(check)

    stairs = sub.add_parser("stairs", help="계단 단높이·디딤판 검사")
    stairs.add_argument("--riser", type=float, required=True, help="단높이(cm)")
    stairs.add_argument("--tread", type=float, required=True, help="디딤판(cm)")
    stairs.add_argument("--floor-height", type=float, help="층고(cm)")
    stairs.add_argument("--width", type=float, help="계단 유효너비(cm)")
    stairs.add_argument("--headroom", type=float, help="계단 유효 높이(cm)")
    _add_common(stairs)

    clutter = sub.add_parser("clutter", help="방 면적 기준 소품 밀도 예산")
    clutter.add_argument("--area", type=float, required=True, help="방 바닥 면적(m^2)")
    clutter.add_argument("--grade", default="normal", choices=sorted(CLUTTER_GRADES))
    clutter.add_argument("--no-nanite", action="store_true", help="비-Nanite 플랫폼(HISM)")
    clutter.add_argument("--materials", type=float, default=1.5, help="소품당 머티리얼 슬롯 수")
    _add_common(clutter)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "presets":
            if args.json:
                print(json.dumps([PRESETS[k].as_dict() for k in PRESETS], ensure_ascii=False, indent=2))
            else:
                print(format_presets())
            return 0

        if args.command == "preset":
            preset = get_preset(args.type)
            if args.json:
                print(json.dumps(preset.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(format_preset(preset))
            return 0

        if args.command == "camera":
            cam = camera_clearance(
                corridor_width=args.corridor,
                ceiling_height=args.ceiling,
                arm_length=args.arm,
                probe_size=args.probe,
                pitch_deg=args.pitch,
                shoulder_offset=args.shoulder,
                eye_height=args.eye,
            )
            print(json.dumps(cam.as_dict(), ensure_ascii=False, indent=2) if args.json else format_camera(cam))
            return 0

        if args.command == "check":
            preset = get_preset(args.preset)
            corridor = preset.corridor_standard if args.corridor is None else args.corridor
            door = preset.door_width if args.door is None else args.door
            door_height = preset.door_height if args.door_height is None else args.door_height
            ceiling = preset.ceiling if args.ceiling is None else args.ceiling
            arm = preset.camera_arm if args.arm is None else args.arm
            riser = preset.stair_riser if args.stair_riser is None else args.stair_riser
            tread = preset.stair_tread if args.stair_tread is None else args.stair_tread
            report = analyze_space(
                corridor_width=corridor,
                door_width=door,
                door_height=door_height,
                ceiling_height=ceiling,
                preset=args.preset,
                arm_length=arm,
                probe_size=args.probe,
                pitch_deg=args.pitch,
                shoulder_offset=args.shoulder,
                capsule_radius=args.capsule_radius,
                capsule_height=args.capsule_height,
                eye_height=args.eye,
                crouch_height=args.crouch,
                stair_riser=riser,
                stair_tread=tread,
            )
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else format_space(report))
            return 0

        if args.command == "stairs":
            report = check_stairs(
                riser=args.riser,
                tread=args.tread,
                floor_height=args.floor_height,
                width=args.width,
                headroom=args.headroom,
            )
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else format_stairs(report))
            return 0

        if args.command == "clutter":
            budget = clutter_budget(
                area_m2=args.area,
                grade=args.grade,
                nanite=not args.no_nanite,
                materials_per_prop=args.materials,
            )
            print(json.dumps(budget.as_dict(), ensure_ascii=False, indent=2) if args.json else format_clutter(budget))
            return 0

        parser.error("unknown command")
        return 2

    except MetricError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
