#!/usr/bin/env python3
"""오픈월드 제작 계획용 계산기와 체크리스트 검증기.

오픈월드 제작에서 실제로 사고를 망치는 것은 취향이 아니라 숫자다.
셀 크기와 로딩 반경이 플레이어 이동 속도와 맞지 않으면 스트리밍 히치가 나고,
랜드스케이프 정점 간격과 권장 크기를 무시하면 컴포넌트 수가 폭발하며,
RVT 해상도를 감으로 잡으면 비디오 메모리가 예산을 넘는다.
이 모듈은 그 숫자들을 프로젝트 착수 전에 손으로 계산하지 않도록
순수 함수로 분리해 두었다. 외부 의존성은 없다.

제공하는 것
  grid       월드 크기 / 셀 크기 / 로딩 반경 -> 셀 수, 동시 로드 셀 수, 스트리밍 처리량
  landscape  목표 크기 / 정점 간격 -> 권장 랜드스케이프 크기, 컴포넌트·드로우콜, 높이 정밀도
  rvt        월드 크기 / 텍셀 밀도 -> RVT 해상도, 타일 수, 밉 포함 메모리, 풀 추정
  hlod       HLOD 레이어 목록 -> 레이어별 HLOD 액터 수, 동시 로드 수, 빌드 리스크
  checklist  프로젝트 상태 JSON -> 필수 항목 누락/실패와 준비도 점수

사용 예:
    # 8 km x 8 km, 256 m 셀, 768 m 로딩 반경
    python pipeline/open_world_helper.py grid --world-km 8 --cell-m 256 --loading-range-m 768

    # 8.2 km 월드를 1 m 간격으로
    python pipeline/open_world_helper.py landscape --target-m 8200 --spacing-m 1.0

    # 랜드스케이프 RVT: 8 km, 2 m당 1텍셀, BC1+BC5
    python pipeline/open_world_helper.py rvt --world-m 8129 --texels-per-m 0.5 \
        --layout base_color_normal --tile-size 256

    # 기본 체크리스트를 JSON으로 뽑아 채운 뒤 검증
    python pipeline/open_world_helper.py checklist --print-default > world_status.json
    python pipeline/open_world_helper.py checklist --status world_status.json

계산 근거와 한계는 docs/open_world_creation_pipeline.md 9장에 정리했다.
수치는 계획용 근사치이며, 최종 값은 프로파일링으로 확정한다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- #
# 상수 (언리얼 엔진 기준)
# --------------------------------------------------------------------------- #

UE_UNITS_PER_METER = 100.0          # 1 uu = 1 cm
LANDSCAPE_HEIGHT_STEPS = 1 << 16    # 16-bit heightmap
LANDSCAPE_DEFAULT_Z_SCALE = 100.0   # Z scale 100 -> -256..256 m (512 m 범위)
LANDSCAPE_Z_RANGE_M = 512.0         # 위 값에서의 실제 높이 범위
LANDSCAPE_MAX_COMPONENTS = 1024     # Epic 권장 상한

# Epic "Landscape Technical Guide"의 권장 크기(정점 수). (정점-1)이 컴포넌트로 나누어떨어진다.
LANDSCAPE_SIZES: tuple[int, ...] = (127, 253, 505, 1009, 2017, 4033, 8129)

# 크기별 (섹션당 쿼드, 컴포넌트당 섹션 수). 4 = 2x2 섹션.
LANDSCAPE_PRESETS: dict[int, tuple[int, int]] = {
    127: (63, 4),
    253: (63, 4),
    505: (63, 4),
    1009: (63, 4),
    2017: (63, 4),
    4033: (63, 4),
    8129: (127, 4),
}

# RVT 콘텐츠 레이아웃별 텍셀당 바이트.
# 압축 시 Epic 문서의 포맷 조합: BaseColor=BC1, Normal=BC5, Rough/Spec=BC3, Mask=8bit.
RVT_LAYOUTS: dict[str, tuple[float, float]] = {
    # name: (compressed bytes/texel, uncompressed bytes/texel)
    "base_color": (0.5, 4.0),
    "base_color_normal": (1.5, 8.0),
    "base_color_normal_roughness_specular": (1.5, 12.0),
    "base_color_normal_roughness_specular_mask": (2.5, 13.0),
}

RVT_MAX_TILES = 4096  # "Size of the virtual texture in tiles" 상한

HLOD_LAYER_TYPES = ("instancing", "merged_mesh", "simplified_mesh", "approximated_mesh")

CHECK_STATUSES = ("pass", "fail", "todo", "skip")


class PlanError(ValueError):
    """입력이 물리적으로나 엔진 규칙상 성립하지 않을 때."""


# --------------------------------------------------------------------------- #
# 공통 수학
# --------------------------------------------------------------------------- #

def _require_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PlanError(f"{name} must be a number, got {value!r}")
    if value <= 0 or not math.isfinite(value):
        raise PlanError(f"{name} must be a positive finite number, got {value!r}")
    return float(value)


def next_power_of_two(value: int) -> int:
    """value 이상인 가장 작은 2의 거듭제곱."""
    if value < 1:
        return 1
    return 1 << (int(value) - 1).bit_length()


def cells_in_radius(cell_size_m: float, radius_m: float) -> int:
    """한 스트리밍 소스 주변에서 반경 radius 안에 '일부라도' 걸치는 셀 수.

    셀은 cell_size 정사각형, 소스는 셀 중심에 있다고 본다.
    반경이 셀 크기의 정수배여도 모서리 셀은 원 밖으로 나가므로
    (2R/c+1)^2 보다 작다. 256 m 셀 / 768 m 반경이면 49가 아니라 45다.
    """
    cell = _require_positive("cell_size_m", cell_size_m)
    radius = _require_positive("radius_m", radius_m)
    k = int(math.ceil((radius + cell / 2.0) / cell))
    count = 0
    for i in range(-k, k + 1):
        dx = max(0.0, abs(i) * cell - cell / 2.0)
        for j in range(-k, k + 1):
            dy = max(0.0, abs(j) * cell - cell / 2.0)
            if math.hypot(dx, dy) <= radius + 1e-9:
                count += 1
    return count


# --------------------------------------------------------------------------- #
# 1. 월드 파티션 그리드 / 스트리밍
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GridPlan:
    world_size_m: float
    cell_size_m: float
    loading_range_m: float
    cells_per_axis: int
    total_cells: int
    loaded_cells_per_axis: int
    max_loaded_cells: int
    loaded_fraction: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StreamingEstimate:
    cell_size_m: float
    bytes_per_cell: float
    speed_mps: float
    seconds_per_cell: float
    cells_crossed_per_minute: float
    load_window_s: float
    required_mb_per_s: float
    resident_mb: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_grid(world_size_m: float, cell_size_m: float, loading_range_m: float) -> GridPlan:
    """월드 크기와 셀/로딩 반경으로 런타임 그리드 계획을 만든다.

    world_size_m: 한 변의 길이(정사각 월드 기준). 직사각형은 두 번 호출한다.
    cell_size_m: Runtime Grid의 Cell Size. 기본 예시 256 m.
    loading_range_m: Loading Range. Epic 문서 예시 768 m.
    """
    world = _require_positive("world_size_m", world_size_m)
    cell = _require_positive("cell_size_m", cell_size_m)
    radius = _require_positive("loading_range_m", loading_range_m)

    cells_per_axis = int(math.ceil(world / cell))
    total = cells_per_axis * cells_per_axis
    loaded_axis = 2 * int(math.ceil(radius / cell)) + 1
    max_loaded = cells_in_radius(cell, radius)
    return GridPlan(
        world_size_m=world,
        cell_size_m=cell,
        loading_range_m=radius,
        cells_per_axis=cells_per_axis,
        total_cells=total,
        loaded_cells_per_axis=loaded_axis,
        max_loaded_cells=max_loaded,
        loaded_fraction=max_loaded / total,
    )


def estimate_streaming(
    plan: GridPlan,
    bytes_per_cell: float,
    speed_mps: float = 6.0,
) -> StreamingEstimate:
    """플레이어 속도 기준으로 셀 하나를 몇 초 안에 로드해야 하는지 계산한다.

    load_window_s는 셀이 로딩 반경에 들어온 순간부터 플레이어가 그 셀 경계에
    닿을 때까지의 시간이다. 이 시간 안에 디스크에서 읽고, 역직렬화하고,
    액터를 활성화해야 화면에 빈 셀이 보이지 않는다.
    """
    size = _require_positive("bytes_per_cell", bytes_per_cell)
    speed = _require_positive("speed_mps", speed_mps)
    window = max(0.0, plan.loading_range_m - plan.cell_size_m / 2.0) / speed
    seconds_per_cell = plan.cell_size_m / speed
    resident_mb = plan.max_loaded_cells * size / (1024.0 * 1024.0)
    return StreamingEstimate(
        cell_size_m=plan.cell_size_m,
        bytes_per_cell=size,
        speed_mps=speed,
        seconds_per_cell=seconds_per_cell,
        cells_crossed_per_minute=60.0 / seconds_per_cell,
        load_window_s=window,
        required_mb_per_s=(size / (1024.0 * 1024.0) / window) if window > 0 else float("inf"),
        resident_mb=resident_mb,
    )


# --------------------------------------------------------------------------- #
# 2. 랜드스케이프
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LandscapePlan:
    target_size_m: float
    size_vertices: int
    size_m: float
    vertex_spacing_m: float
    quads_per_section: int
    sections_per_component: int
    component_quads: int
    components_per_axis: int
    total_components: int
    draw_calls: int
    z_scale: float
    height_range_m: float
    height_precision_cm: float
    heightmap_mb: float
    tiles_across: int
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def pick_landscape_size(required_vertices: int) -> int:
    """필요 정점 수 이상인 Epic 권장 크기 중 가장 작은 것."""
    if required_vertices < 1:
        raise PlanError("required_vertices must be >= 1")
    for size in LANDSCAPE_SIZES:
        if size >= required_vertices:
            return size
    raise PlanError(
        f"{required_vertices} vertices exceeds the largest recommended landscape "
        f"({LANDSCAPE_SIZES[-1]}); split into tiles"
    )


def plan_landscape(
    target_size_m: float,
    spacing_m: float = 1.0,
    *,
    quads_per_section: int | None = None,
    sections_per_component: int = 4,
    height_range_m: float = LANDSCAPE_Z_RANGE_M,
    full_resolution: bool = False,
) -> LandscapePlan:
    """목표 월드 크기와 정점 간격으로 랜드스케이프 구성을 계산한다.

    target_size_m: 덮으려는 한 변 길이(m). 예: 8 km -> 8000.
    spacing_m: 정점 간 거리(m). 1 m면 1 m² 당 정점 1개.
    quads_per_section: 섹션당 쿼드. None이면 권장 크기 프리셋을 따른다.
    sections_per_component: 4(2x2) 또는 1. 기본 4.
    height_range_m: 표현할 높이 범위(m). 기본 512 m (Z scale 100).
    full_resolution: Houdini Engine의 'Use Full Resolution'처럼 16bit 전 범위를
        높이에 쓸지. False면 엔진 기본 관행대로 3/4만 사용해 이후 스컬프트 여유를 둔다.
    """
    target = _require_positive("target_size_m", target_size_m)
    spacing = _require_positive("spacing_m", spacing_m)
    if sections_per_component not in (1, 4):
        raise PlanError("sections_per_component must be 1 or 4 (2x2)")
    if height_range_m <= 0:
        raise PlanError("height_range_m must be positive")

    required = int(math.floor(target / spacing)) + 1
    tiles = 1
    if required > LANDSCAPE_SIZES[-1]:
        # 한 장으로 안 되는 크기: 타일 수를 올리고 타일당 크기를 다시 고른다.
        tiles = int(math.ceil((required - 1) / (LANDSCAPE_SIZES[-1] - 1)))
        size = pick_landscape_size(int(math.ceil(target / tiles / spacing)) + 1)
    else:
        size = pick_landscape_size(required)

    preset_quads, _ = LANDSCAPE_PRESETS[size]
    quads = preset_quads if quads_per_section is None else int(quads_per_section)
    if quads not in (7, 15, 31, 63, 127, 255):
        raise PlanError("quads_per_section must be one of 7, 15, 31, 63, 127, 255")

    component_quads = quads * (2 if sections_per_component == 4 else 1)
    quads_total = size - 1
    if quads_total % component_quads != 0:
        raise PlanError(
            f"{size} vertices ({quads_total} quads) is not divisible by "
            f"{component_quads} quads per component; pick another size or section setting"
        )
    components_axis = quads_total // component_quads
    total_components = components_axis * components_axis

    warnings: list[str] = []
    if total_components > LANDSCAPE_MAX_COMPONENTS:
        warnings.append(
            f"{total_components} components exceeds Epic's recommended {LANDSCAPE_MAX_COMPONENTS}; "
            "split into tiles or lower vertex density"
        )
    if tiles > 1:
        warnings.append(
            f"world needs {tiles}x{tiles} landscape tiles; adjacent tiles must share edge vertices"
        )

    actual_spacing = target / tiles / (size - 1)
    precision = height_range_m * 100.0 / (LANDSCAPE_HEIGHT_STEPS * (1.0 if full_resolution else 0.75))
    return LandscapePlan(
        target_size_m=target,
        size_vertices=size,
        size_m=(size - 1) * actual_spacing,
        vertex_spacing_m=actual_spacing,
        quads_per_section=quads,
        sections_per_component=sections_per_component,
        component_quads=component_quads,
        components_per_axis=components_axis,
        total_components=total_components,
        draw_calls=total_components * sections_per_component,
        z_scale=height_range_m * 100.0 / LANDSCAPE_Z_RANGE_M,
        height_range_m=height_range_m,
        height_precision_cm=precision,
        heightmap_mb=size * size * 2 / 1_000_000.0,
        tiles_across=tiles,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------- #
# 3. Runtime Virtual Texture
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RvtBudget:
    world_size_m: float
    tile_size: int
    max_tiles_per_axis: int
    requested_texels_per_m: float
    tiles_per_axis: int
    resolution: int
    effective_texels_per_m: float
    meters_per_texel: float
    tiles_mip0: int
    tiles_all_mips: int
    bytes_per_texel: float
    mip0_mb: float
    all_mips_mb: float
    page_table_mb: float
    pool_estimate_mb: float
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_rvt(
    world_size_m: float,
    texels_per_m: float,
    *,
    tile_size: int = 256,
    max_tiles_per_axis: int = 64,
    layout: str = "base_color_normal_roughness_specular",
    compressed: bool = True,
    pool_coverage: float = 0.35,
) -> RvtBudget:
    """랜드스케이프를 덮는 RVT 한 장의 해상도와 메모리를 계산한다.

    world_size_m: RVT 볼륨이 덮는 한 변 길이(m).
    texels_per_m: 요구 텍셀 밀도. 0.5 = 2 m마다 1텍셀.
    tile_size: Physical tile 한 변(texel). 128 또는 256이 일반적.
    max_tiles_per_axis: Virtual texture의 축당 타일 수(2의 거듭제곱).
        64 x 256 = 16384 texel까지. Epic 상한은 타일 총 4096개.
    layout: RVT_LAYOUTS 키.
    compressed: BC 압축 사용 여부. 끄면 4~8배 메모리.
    pool_coverage: 동시에 상주한다고 보는 mip0 비율(0~1). 풀 크기 추정용.
    """
    world = _require_positive("world_size_m", world_size_m)
    density = _require_positive("texels_per_m", texels_per_m)
    if tile_size not in (64, 128, 256, 512):
        raise PlanError("tile_size must be 64, 128, 256 or 512")
    if max_tiles_per_axis < 1 or max_tiles_per_axis > 256:
        raise PlanError("max_tiles_per_axis must be between 1 and 256")
    if max_tiles_per_axis & (max_tiles_per_axis - 1):
        raise PlanError("max_tiles_per_axis must be a power of two")
    if layout not in RVT_LAYOUTS:
        raise PlanError(f"unknown layout {layout!r}; choose from {sorted(RVT_LAYOUTS)}")
    if not 0 < pool_coverage <= 1:
        raise PlanError("pool_coverage must be in (0, 1]")

    warnings: list[str] = []
    total_tiles = max_tiles_per_axis * max_tiles_per_axis
    if total_tiles > RVT_MAX_TILES:
        raise PlanError(
            f"{max_tiles_per_axis} tiles per axis = {total_tiles} tiles, above the "
            f"{RVT_MAX_TILES}-tile limit"
        )

    requested_res = world * density
    needed_tiles = int(math.ceil(requested_res / tile_size))
    tiles_axis = min(max_tiles_per_axis, max(1, next_power_of_two(needed_tiles)))
    if needed_tiles > max_tiles_per_axis:
        warnings.append(
            f"requested {requested_res:.0f} texels per axis exceeds the "
            f"{max_tiles_per_axis * tile_size} texel maximum; density is clamped"
        )
    resolution = tiles_axis * tile_size
    compressed_bpt, raw_bpt = RVT_LAYOUTS[layout]
    bpt = compressed_bpt if compressed else raw_bpt
    if not compressed:
        warnings.append(
            "uncompressed RVT costs 4-8x the memory; use it only for debugging or quality comparison"
        )
    effective = resolution / world
    if effective < 0.1:
        warnings.append(
            f"{1 / effective:.1f} m per texel is very coarse for a landscape; "
            "expect blurry ground up close"
        )

    tiles_mip0 = tiles_axis * tiles_axis
    tiles_all = int(tiles_mip0 * 4 / 3)  # mip 체인의 타일 합은 4/3에 수렴
    mip0_bytes = resolution * resolution * bpt
    all_bytes = mip0_bytes * 4 / 3
    page_table_bytes = tiles_all * 4  # RGBA8 한 텍셀 = 한 타일
    pool_mb = mip0_bytes * pool_coverage / (1024.0 * 1024.0)

    return RvtBudget(
        world_size_m=world,
        tile_size=tile_size,
        max_tiles_per_axis=max_tiles_per_axis,
        requested_texels_per_m=density,
        tiles_per_axis=tiles_axis,
        resolution=resolution,
        effective_texels_per_m=effective,
        meters_per_texel=1.0 / effective,
        tiles_mip0=tiles_mip0,
        tiles_all_mips=tiles_all,
        bytes_per_texel=bpt,
        mip0_mb=mip0_bytes / (1024.0 * 1024.0),
        all_mips_mb=all_bytes / (1024.0 * 1024.0),
        page_table_mb=page_table_bytes / (1024.0 * 1024.0),
        pool_estimate_mb=pool_mb,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------- #
# 4. HLOD
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class HlodLayerPlan:
    name: str
    layer_type: str
    cell_size_m: float
    loading_range_m: float
    cells_per_axis: int
    total_actors: int
    concurrent_actors: int
    cells_per_world_cell: float
    estimated_build_minutes: float
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_hlod(
    world_size_m: float,
    world_cell_size_m: float,
    layers: Sequence[Mapping[str, Any]],
    *,
    build_seconds_per_actor: float = 1.5,
) -> tuple[HlodLayerPlan, ...]:
    """HLOD 레이어별 프록시 액터 수와 빌드 비용을 계산한다.

    layers: [{"name": "HLOD0", "layer_type": "instancing",
              "cell_size_m": 256, "loading_range_m": 512}, ...]
    build_seconds_per_actor: 프록시 1개 빌드에 드는 대략적 시간.
        병합/단순화 레이어는 훨씬 비싸므로 프로젝트에서 보정한다.
    """
    world = _require_positive("world_size_m", world_size_m)
    world_cell = _require_positive("world_cell_size_m", world_cell_size_m)
    if not layers:
        raise PlanError("at least one HLOD layer is required")

    plans: list[HlodLayerPlan] = []
    for index, raw in enumerate(layers):
        name = str(raw.get("name") or f"HLOD{index}")
        layer_type = str(raw.get("layer_type", "instancing"))
        if layer_type not in HLOD_LAYER_TYPES:
            raise PlanError(f"{name}: unknown layer_type {layer_type!r}")
        cell = _require_positive(f"{name}.cell_size_m", raw.get("cell_size_m", world_cell * 2))
        rng = _require_positive(f"{name}.loading_range_m", raw.get("loading_range_m", cell * 2))

        cells_axis = int(math.ceil(world / cell))
        total = cells_axis * cells_axis
        concurrent = cells_in_radius(cell, rng)
        warnings: list[str] = []
        if abs((cell / world_cell) - round(cell / world_cell)) > 1e-9:
            warnings.append(
                f"cell {cell:g} m is not a multiple of the {world_cell:g} m world cell; "
                "HLOD proxies will straddle streaming cells"
            )
        if cell * 2 > rng:
            warnings.append(
                "loading range is less than two HLOD cells; proxies pop in at the horizon"
            )
        if total > 50_000:
            warnings.append(
                f"{total} proxy actors: full rebuilds take hours; use rebuild policies and a build farm"
            )
        plans.append(
            HlodLayerPlan(
                name=name,
                layer_type=layer_type,
                cell_size_m=cell,
                loading_range_m=rng,
                cells_per_axis=cells_axis,
                total_actors=total,
                concurrent_actors=concurrent,
                cells_per_world_cell=(cell / world_cell) ** 2,
                estimated_build_minutes=total * build_seconds_per_actor / 60.0,
                warnings=tuple(warnings),
            )
        )
    return tuple(plans)


# --------------------------------------------------------------------------- #
# 5. 체크리스트
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CheckItem:
    id: str
    category: str
    title: str
    detail: str
    required: bool = True
    weight: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_CHECKLIST: tuple[CheckItem, ...] = (
    # --- 좌표계 / 공간 ---
    CheckItem("coord.lwc", "좌표계", "Large World Coordinates 예산 확정",
              "월드 최대 좌표가 2^43 cm(약 88M km) 안인지, 원점에서 먼 곳의 정밀도(점 단위 오차)를 확인했다.", weight=3),
    CheckItem("coord.float_systems", "좌표계", "단정밀 예외 시스템 목록화",
              "Niagara, 일부 물리/서드파티처럼 여전히 float를 쓰는 시스템의 좌표 한계를 문서화했다.", weight=2),
    CheckItem("coord.origin", "좌표계", "월드 원점과 플레이 영역 정렬",
              "플레이 영역이 원점에서 지나치게 멀지 않은지, 텔레포트·시네마틱 카메라 컷에서 좌표 점프가 없는지 확인했다.", weight=2),
    # --- 지형 ---
    CheckItem("terrain.source", "지형", "하이트맵 소스와 침식 시뮬레이션 확정",
              "Houdini/World Machine/Gaea에서 지질학적 침식(Hydraulic/Thermal)을 적용하고, 최종 하이트맵을 16-bit로 익스포트했다.", weight=3),
    CheckItem("terrain.size", "지형", "랜드스케이프 크기/간격/컴포넌트 검증",
              "권장 크기(2017/4033/8129 등)를 쓰고 컴포넌트 1024개 이하, 정점 간격과 목표 해상도가 일치한다.", weight=3),
    CheckItem("terrain.seams", "지형", "타일 경계와 심(seam) 제거",
              "타일 간 경계 정점이 일치하고, LOD 전환·노멀·RVT 경계에서 이음매가 보이지 않는다.", weight=2),
    CheckItem("terrain.collision", "지형", "콜리전과 플레이 가능 영역",
              "랜드스케이프 콜리전, 경사도 제한, 낙하/수영 경계가 게임플레이와 맞는다.", weight=2),
    CheckItem("terrain.masks", "지형", "레이어 마스크와 가중치 페인팅 규칙",
              "바이옴/암반/모래/눈 마스크가 8-bit 레이어로 정리되고, 가중치 합이 정규화되어 있다.", weight=2),
    # --- 머티리얼 / RVT ---
    CheckItem("material.rvt_layout", "머티리얼", "RVT 레이아웃과 압축 예산 확정",
              "BaseColor/Normal/Roughness/Specular/Mask 중 필요한 것만 RVT에 넣고 BC 압축을 켰다. 텍셀당 바이트와 메모리를 계산해 두었다.", weight=3),
    CheckItem("material.rvt_pool", "머티리얼", "RVT/VT 풀 크기 프로파일링",
              "cooked 빌드의 Fixed Pool 크기를 정하고 stat virtualtexturing / stat virtualtexturememory로 eviction이 없는지 확인했다.", weight=2),
    CheckItem("material.slope_blend", "머티리얼", "경사/고도 기반 자동 블렌딩",
              "Slope·Height·Noise 기반 레이어 블렌딩이 원경에서도 타일링이 보이지 않게 구성됐다.", weight=2),
    CheckItem("material.displacement", "머티리얼", "변위/디테일 메시 전략",
              "VHM, Nanite displacement, Mesh Terrain 중 무엇을 쓸지 정했고, 충돌과 렌더 비용을 검증했다.", weight=2),
    # --- 스트리밍 ---
    CheckItem("streaming.grid", "스트리밍", "런타임 그리드 셀 크기 결정",
              "플레이어 이동 속도·시야·셀당 데이터량으로 셀 크기를 정하고, 셀 경계를 넘을 때 히치가 없음을 확인했다.", weight=3),
    CheckItem("streaming.range", "스트리밍", "로딩 반경과 시야 거리 정합",
              "Loading Range가 카메라 시야/HLOD 전환 거리보다 충분히 앞서고, 로딩 완료 전에 셀이 화면에 들어오지 않는다.", weight=3),
    CheckItem("streaming.data_layers", "스트리밍", "데이터 레이어 분리",
              "낮/밤, 퀘스트 단계, 파괴 상태, 계절 등 상태 분기를 Data Layer로 분리하고 런타임 활성화 비용을 측정했다.", weight=2),
    CheckItem("streaming.ofpa", "스트리밍", "OFPA와 버전 관리 규칙",
              "One File Per Actor로 저장되고, .uasset 잠금/충돌 규칙과 LFS 사용 여부를 팀에 공지했다.", weight=2),
    CheckItem("streaming.sources", "스트리밍", "스트리밍 소스와 프리로드",
              "텔레포트 지점, 컷신, 빠른 이동에 Streaming Source Component를 배치하고 Is Streaming Completed로 대기한다.", weight=2),
    CheckItem("streaming.fgs", "스트리밍", "Fast Geometry Streaming 검토",
              "비게임플레이 정적 지오메트리를 Fast Geometry Streaming으로 분리할 수 있는지 검토했다(5.8 실험).", weight=1, required=False),
    # --- PCG / 식생 ---
    CheckItem("pcg.biome", "PCG", "바이옴 맵과 규칙 확정",
              "기온/습도(Whittaker) 기반 바이옴 경계와 종 분포를 정의하고, 바이옴 마스크를 텍스처/스플라인/랜드스케이프 레이어로 공급한다.", weight=3),
    CheckItem("pcg.graphs", "PCG", "PCG 그래프 버전 관리와 재현성",
              "그래프·시드·파라미터가 소스 컨트롤에 있고, 같은 입력에서 같은 결과가 나오는지 확인했다.", weight=3),
    CheckItem("pcg.density", "PCG", "인스턴스 밀도 예산",
              "100 m²당 인스턴스 수, 화면 내 최대 인스턴스, HISM 배칭 단위를 정하고 실측했다.", weight=3),
    CheckItem("pcg.runtime", "PCG", "런타임 생성 vs 베이킹 결정",
              "PCG Partition과 런타임 생성 여부를 정하고, generated actor 수와 GC/스트리밍 영향을 측정했다.", weight=2),
    CheckItem("pcg.wind", "PCG", "식생 바람과 그림자",
              "WPO/스키닝 기반 바람, Nanite foliage voxel, 그림자 캐스터 비용을 검증했다.", weight=2),
    # --- 인프라 ---
    CheckItem("infra.roads", "인프라", "도로/스플라인 인프라",
              "Landscape Spline 또는 PCG Spline Sampler로 도로·강을 깔고, 랜드스케이프 디폼과 교차로 처리를 검증했다.", weight=2),
    CheckItem("infra.water", "인프라", "수계와 부력",
              "Water Body(호수/강/바다) 토폴로지가 연결되고, Gerstner 파도·수중 렌더링·부력이 게임플레이와 맞는다.", weight=2),
    # --- 라이팅 ---
    CheckItem("lighting.sky", "라이팅", "대기/구름/안개 기준 설정",
              "Sky Atmosphere, Volumetric Cloud, Exponential Height Fog의 기준 시간대와 노출을 고정했다.", weight=2),
    CheckItem("lighting.lumen", "라이팅", "Lumen 경로와 Far Field",
              "SW/HW 레이트레이싱 선택, Lumen Scene 거리(200~800 m), Far Field(HLOD1 필요) 사용 여부를 정했다.", weight=3),
    CheckItem("lighting.vsm", "라이팅", "VSM 캐시와 그림자 예산",
              "가상 섀도우 맵 페이지 풀, 캐시 무효화, 원거리 그림자 캐스터 비용을 프로파일링했다.", weight=2),
    CheckItem("lighting.tod", "라이팅", "시간대 순환",
              "태양 각도·색·노출 곡선, 밤 조명 전환, 그림자 캐시 갱신 비용을 하루 전체에서 확인했다.", weight=2),
    # --- 최적화 ---
    CheckItem("perf.budget", "최적화", "프레임/메모리 예산 문서화",
              "타깃 기기별 GPU/CPU 프레임 예산과 VRAM/스트리밍 예산을 숫자로 정했다.", weight=3),
    CheckItem("perf.hlod", "최적화", "HLOD 레이어와 빌드 파이프라인",
              "레이어 타입/셀/로딩 반경을 정하고, Build HLODs 또는 WorldPartitionHLODsBuilder를 CI에 연결했다.", weight=3),
    CheckItem("perf.culling", "최적화", "컬링 전략",
              "HZB 오클루전, Distance Cull, Precomputed Visibility, Cull Distance Volume의 조합을 검증했다.", weight=2),
    CheckItem("perf.texture_pool", "최적화", "텍스처 스트리밍 풀",
              "r.Streaming.PoolSize와 VT 풀을 기기 프로파일별로 정하고 stat streaming으로 확인했다.", weight=2),
    CheckItem("perf.trace", "최적화", "Unreal Insights 트레이스",
              "Spatial Profiler로 셀 단위 스트리밍을, GPU Visualizer/stat gpu로 렌더 비용을 기록했다.", weight=2),
    CheckItem("perf.hitch", "최적화", "히치 스냅샷과 재현 시나리오",
              "snapshothitches로 히치를 수집하고, 최악 동선(고속 이동·텔레포트)에서 재현했다.", weight=2),
    # --- 빌드 ---
    CheckItem("build.cook", "빌드", "쿡/패키징 검증",
              "에디터가 아닌 cooked 빌드에서 스트리밍, RVT, PCG, HLOD가 동작하는지 확인했다.", weight=3),
    CheckItem("build.profiles", "빌드", "플랫폼 프로파일",
              "각 타깃 기기의 Device Profile과 Scalability 그룹에서 Lumen/VSM/foliage 품질이 의도대로 떨어진다.", weight=2),
    CheckItem("build.automation", "빌드", "자동화된 야간 빌드",
              "HLOD 빌드·쿡·프로파일 캡처를 자동화하고, 회귀 지표를 대시보드에서 본다.", weight=1, required=False),
)


@dataclass(frozen=True)
class ChecklistReport:
    ready: bool
    score: float
    total_items: int
    passed: int
    failed: int
    todo: int
    skipped: int
    blockers: tuple[str, ...]
    unknown_ids: tuple[str, ...]
    by_category: Mapping[str, Mapping[str, int]]
    notes: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_status(value: Any) -> tuple[str, str]:
    if isinstance(value, str):
        status, note = value, ""
    elif isinstance(value, Mapping):
        status = str(value.get("status", "todo"))
        note = str(value.get("note", ""))
    else:
        raise PlanError(f"invalid checklist entry {value!r}")
    if status not in CHECK_STATUSES:
        raise PlanError(f"invalid status {status!r}; use one of {CHECK_STATUSES}")
    return status, note


def evaluate_checklist(
    statuses: Mapping[str, Any],
    items: Sequence[CheckItem] = DEFAULT_CHECKLIST,
) -> ChecklistReport:
    """프로젝트 상태를 기본 체크리스트와 대조해 준비도를 계산한다.

    statuses: {item_id: "pass" | "fail" | "todo" | "skip" | {"status":..., "note":...}}
    누락된 항목은 todo로 본다. 필수 항목이 pass가 아니면 ready=False.
    점수는 skip을 제외한 가중치 대비 pass 비율이다.
    """
    by_id = {item.id: item for item in items}
    unknown = tuple(sorted(set(statuses) - set(by_id)))
    resolved: dict[str, str] = {}
    notes: dict[str, str] = {}
    for item_id in by_id:
        raw = statuses.get(item_id, "todo")
        status, note = _normalize_status(raw)
        resolved[item_id] = status
        if note:
            notes[item_id] = note

    passed = sum(1 for s in resolved.values() if s == "pass")
    failed = sum(1 for s in resolved.values() if s == "fail")
    todo = sum(1 for s in resolved.values() if s == "todo")
    skipped = sum(1 for s in resolved.values() if s == "skip")

    weight_total = 0
    weight_pass = 0
    blockers: list[str] = []
    by_category: dict[str, dict[str, int]] = {}
    for item in items:
        status = resolved[item.id]
        bucket = by_category.setdefault(item.category, {"pass": 0, "fail": 0, "todo": 0, "skip": 0})
        bucket[status] += 1
        if status != "skip":
            weight_total += item.weight
            if status == "pass":
                weight_pass += item.weight
        if item.required and status != "pass":
            blockers.append(f"{item.id} ({status}): {item.title}")

    score = (weight_pass / weight_total * 100.0) if weight_total else 100.0
    return ChecklistReport(
        ready=not blockers,
        score=round(score, 1),
        total_items=len(items),
        passed=passed,
        failed=failed,
        todo=todo,
        skipped=skipped,
        blockers=tuple(blockers),
        unknown_ids=unknown,
        by_category=by_category,
        notes=notes,
    )


def load_status_file(path: Path | str) -> Mapping[str, Any]:
    """체크리스트 상태 JSON을 읽는다. {"items": {...}} 또는 {...} 둘 다 허용."""
    p = Path(path)
    if not p.exists():
        raise PlanError(f"file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"invalid JSON in {p}: {exc}") from exc
    if isinstance(data, Mapping) and isinstance(data.get("items"), Mapping):
        return data["items"]
    if isinstance(data, Mapping):
        return data
    raise PlanError(f"{p} must contain a JSON object of item_id -> status")


def default_status_template() -> dict[str, Any]:
    """모든 항목이 todo인 상태 파일 템플릿."""
    return {
        "project": "",
        "engine_version": "5.8",
        "items": {
            item.id: {"status": "todo", "note": ""}
            for item in DEFAULT_CHECKLIST
        },
    }


# --------------------------------------------------------------------------- #
# 텍스트 출력
# --------------------------------------------------------------------------- #

def format_grid(plan: GridPlan, estimate: StreamingEstimate | None = None) -> str:
    lines = [
        f"월드 {plan.world_size_m:,.0f} m  |  셀 {plan.cell_size_m:g} m  |  로딩 반경 {plan.loading_range_m:g} m",
        f"  그리드            {plan.cells_per_axis} x {plan.cells_per_axis} = {plan.total_cells:,} 셀",
        f"  동시 로드 셀      최대 {plan.max_loaded_cells}개 "
        f"({plan.loaded_cells_per_axis}x{plan.loaded_cells_per_axis} 정사각형의 모서리 제외)",
        f"  월드 대비         {plan.loaded_fraction * 100:.2f}%",
    ]
    if estimate:
        lines += [
            f"  셀 통과 시간      {estimate.seconds_per_cell:.1f} s  "
            f"(분당 {estimate.cells_crossed_per_minute:.1f} 셀, {estimate.speed_mps:g} m/s)",
            f"  로드 윈도우       {estimate.load_window_s:.1f} s",
            f"  셀 데이터         {estimate.bytes_per_cell / (1024 * 1024):.1f} MB  "
            f"-> 필요 처리량 {estimate.required_mb_per_s:.1f} MB/s",
            f"  상주 추정         {estimate.resident_mb:,.0f} MB",
        ]
    return "\n".join(lines)


def format_landscape(plan: LandscapePlan) -> str:
    lines = [
        f"목표 {plan.target_size_m:,.0f} m  |  {plan.size_vertices}x{plan.size_vertices} 정점  "
        f"({plan.size_m:,.0f} m, {plan.vertex_spacing_m:.2f} m 간격)",
        f"  타일              {plan.tiles_across}x{plan.tiles_across}",
        f"  섹션/컴포넌트     {plan.quads_per_section} 쿼드 x {plan.sections_per_component} 섹션 "
        f"= {plan.component_quads} 쿼드",
        f"  컴포넌트          {plan.components_per_axis}x{plan.components_per_axis} = {plan.total_components:,}개",
        f"  드로우콜(섹션)    최대 {plan.draw_calls:,}",
        f"  Z scale           {plan.z_scale:.2f}  (높이 범위 {plan.height_range_m:g} m)",
        f"  높이 정밀도       {plan.height_precision_cm:.2f} cm",
        f"  하이트맵          {plan.heightmap_mb:,.1f} MB (16-bit raw)",
    ]
    lines += [f"  [경고] {w}" for w in plan.warnings]
    return "\n".join(lines)


def format_rvt(budget: RvtBudget) -> str:
    lines = [
        f"월드 {budget.world_size_m:,.0f} m  |  타일 {budget.tile_size} texel  "
        f"|  최대 {budget.max_tiles_per_axis} 타일/축",
        f"  해상도            {budget.resolution}x{budget.resolution} "
        f"({budget.tiles_per_axis}x{budget.tiles_per_axis} 타일)",
        f"  실제 밀도         {budget.effective_texels_per_m:.3f} texel/m "
        f"({budget.meters_per_texel:.2f} m/texel)",
        f"  텍셀당 바이트     {budget.bytes_per_texel:g} B",
        f"  Mip0 메모리       {budget.mip0_mb:,.1f} MB",
        f"  전체 밉 포함      {budget.all_mips_mb:,.1f} MB",
        f"  페이지 테이블     {budget.page_table_mb * 1024:,.1f} KB ({budget.tiles_all_mips:,} 타일)",
        f"  풀 추정           {budget.pool_estimate_mb:,.1f} MB "
        f"(mip0의 일부만 상주한다는 가정)",
    ]
    lines += [f"  [경고] {w}" for w in budget.warnings]
    return "\n".join(lines)


def format_hlod(plans: Iterable[HlodLayerPlan]) -> str:
    lines = []
    total_actors = 0
    total_minutes = 0.0
    for p in plans:
        total_actors += p.total_actors
        total_minutes += p.estimated_build_minutes
        lines.append(
            f"{p.name:<8} {p.layer_type:<16} 셀 {p.cell_size_m:>6g} m  반경 {p.loading_range_m:>6g} m  "
            f"-> {p.total_actors:>7,} 액터 (동시 {p.concurrent_actors:>3}), "
            f"월드 셀당 {p.cells_per_world_cell:g}개, 빌드 ~{p.estimated_build_minutes:.0f}분"
        )
        lines += [f"  [경고] {w}" for w in p.warnings]
    lines.append(f"합계: {total_actors:,} 프록시 액터, 전체 빌드 ~{total_minutes / 60:.1f}시간(1코어 기준)")
    return "\n".join(lines)


def format_checklist(report: ChecklistReport) -> str:
    head = "READY" if report.ready else "NOT READY"
    lines = [
        f"{head}  |  준비도 {report.score:.1f}%  "
        f"(pass {report.passed}, fail {report.failed}, todo {report.todo}, skip {report.skipped} / {report.total_items})",
    ]
    for category, counts in report.by_category.items():
        lines.append(
            f"  {category:<6} pass {counts['pass']:>2}  fail {counts['fail']:>2}  "
            f"todo {counts['todo']:>2}  skip {counts['skip']:>2}"
        )
    if report.blockers:
        lines.append("블로커:")
        lines += [f"  - {b}" for b in report.blockers]
    if report.unknown_ids:
        lines.append("알 수 없는 항목 id(무시됨): " + ", ".join(report.unknown_ids))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="텍스트 대신 JSON으로 출력")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open_world_helper",
        description="오픈월드 제작 계획 계산기 (UE5 World Partition / Landscape / RVT / HLOD)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    grid = sub.add_parser("grid", help="월드 파티션 그리드와 스트리밍 처리량")
    grid.add_argument("--world-km", type=float, required=True, help="월드 한 변(km)")
    grid.add_argument("--cell-m", type=float, default=256.0, help="셀 크기(m), 기본 256")
    grid.add_argument("--loading-range-m", type=float, default=768.0, help="로딩 반경(m), 기본 768")
    grid.add_argument("--bytes-per-cell", type=float, help="셀 하나의 데이터량(bytes). 주면 처리량 계산")
    grid.add_argument("--speed-mps", type=float, default=6.0, help="플레이어 이동 속도(m/s), 기본 6")
    _add_common(grid)

    land = sub.add_parser("landscape", help="랜드스케이프 크기·컴포넌트·높이 정밀도")
    land.add_argument("--target-m", type=float, required=True, help="덮을 한 변 길이(m)")
    land.add_argument("--spacing-m", type=float, default=1.0, help="정점 간격(m), 기본 1")
    land.add_argument("--quads-per-section", type=int, help="섹션당 쿼드(기본: 권장 프리셋)")
    land.add_argument("--sections-per-component", type=int, choices=(1, 4), default=4)
    land.add_argument("--height-range-m", type=float, default=LANDSCAPE_Z_RANGE_M)
    land.add_argument("--full-resolution", action="store_true", help="16bit 전 범위 사용")
    _add_common(land)

    rvt = sub.add_parser("rvt", help="RVT 해상도와 메모리 예산")
    rvt.add_argument("--world-m", type=float, required=True, help="RVT가 덮는 한 변(m)")
    rvt.add_argument("--texels-per-m", type=float, required=True, help="요구 텍셀 밀도(0.5 = 2 m/texel)")
    rvt.add_argument("--tile-size", type=int, default=256, choices=(64, 128, 256, 512))
    rvt.add_argument("--max-tiles-per-axis", type=int, default=64)
    rvt.add_argument("--layout", default="base_color_normal_roughness_specular", choices=sorted(RVT_LAYOUTS))
    rvt.add_argument("--uncompressed", action="store_true")
    rvt.add_argument("--pool-coverage", type=float, default=0.35)
    _add_common(rvt)

    hlod = sub.add_parser("hlod", help="HLOD 레이어별 프록시 수와 빌드 비용")
    hlod.add_argument("--world-km", type=float, required=True)
    hlod.add_argument("--world-cell-m", type=float, default=256.0)
    hlod.add_argument("--layer", action="append", metavar="NAME:TYPE:CELL_M:RANGE_M",
                      help="예: HLOD0:instancing:51200:102400 (여러 번 사용)")
    hlod.add_argument("--build-seconds-per-actor", type=float, default=1.5)
    _add_common(hlod)

    check = sub.add_parser("checklist", help="오픈월드 준비 상태 검증")
    check.add_argument("--status", type=Path, help="상태 JSON 경로")
    check.add_argument("--print-default", action="store_true", help="todo 템플릿을 출력하고 종료")
    check.add_argument("--list-items", action="store_true", help="체크리스트 항목 목록 출력")
    check.add_argument("--json", action="store_true")

    return parser


def _parse_layers(raw: Sequence[str] | None) -> list[dict[str, Any]]:
    if not raw:
        # 기본 2단 HLOD: 근거리 병합/단순화, 원거리 인스턴싱
        return [
            {"name": "HLOD0", "layer_type": "simplified_mesh", "cell_size_m": 512.0, "loading_range_m": 1024.0},
            {"name": "HLOD1", "layer_type": "instancing", "cell_size_m": 2048.0, "loading_range_m": 4096.0},
        ]
    layers = []
    for item in raw:
        parts = item.split(":")
        if len(parts) != 4:
            raise PlanError(f"--layer must be NAME:TYPE:CELL_M:RANGE_M, got {item!r}")
        name, layer_type, cell, rng = parts
        layers.append({
            "name": name,
            "layer_type": layer_type,
            "cell_size_m": float(cell),
            "loading_range_m": float(rng),
        })
    return layers


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "grid":
            plan = calculate_grid(args.world_km * 1000.0, args.cell_m, args.loading_range_m)
            est = None
            if args.bytes_per_cell:
                est = estimate_streaming(plan, args.bytes_per_cell, args.speed_mps)
            if args.json:
                payload = plan.as_dict()
                if est:
                    payload["streaming"] = est.as_dict()
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(format_grid(plan, est))

        elif args.command == "landscape":
            plan = plan_landscape(
                args.target_m,
                args.spacing_m,
                quads_per_section=args.quads_per_section,
                sections_per_component=args.sections_per_component,
                height_range_m=args.height_range_m,
                full_resolution=args.full_resolution,
            )
            if args.json:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(format_landscape(plan))

        elif args.command == "rvt":
            budget = calculate_rvt(
                args.world_m,
                args.texels_per_m,
                tile_size=args.tile_size,
                max_tiles_per_axis=args.max_tiles_per_axis,
                layout=args.layout,
                compressed=not args.uncompressed,
                pool_coverage=args.pool_coverage,
            )
            if args.json:
                print(json.dumps(budget.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(format_rvt(budget))

        elif args.command == "hlod":
            layers = _parse_layers(args.layer)
            plans = plan_hlod(
                args.world_km * 1000.0,
                args.world_cell_m,
                layers,
                build_seconds_per_actor=args.build_seconds_per_actor,
            )
            if args.json:
                print(json.dumps([p.as_dict() for p in plans], ensure_ascii=False, indent=2))
            else:
                print(format_hlod(plans))

        elif args.command == "checklist":
            if args.print_default:
                print(json.dumps(default_status_template(), ensure_ascii=False, indent=2))
                return 0
            if args.list_items:
                for item in DEFAULT_CHECKLIST:
                    flag = "필수" if item.required else "선택"
                    print(f"{item.id:<24} [{item.category}/{flag}] {item.title}")
                return 0
            if not args.status:
                parser.error("checklist requires --status, --print-default, or --list-items")
            report = evaluate_checklist(load_status_file(args.status))
            if args.json:
                print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(format_checklist(report))

        return 0
    except PlanError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
