#!/usr/bin/env python3
"""차량·실내 에셋의 VRAM 예산 계산기와 익스플로전 베이킹/케이지 검증기.

차량 한 대의 텍스처 예산은 "느낌"이 아니라 **곱셈**으로 결정된다.
4096 노멀 한 장이 몇 MiB 인지, 밉 체인을 포함하면 얼마가 더 붙는지,
그 값이 차종 수와 대수에 어떻게 곱해지는지를 손으로 하다 보면
어딘가에서 MiB 와 MB 를 섞거나 밉 체인을 빠뜨린다. 그러면
"18 차종이면 1.4 GB 니까 10 GB 에 충분하다"는 결론은 우연히 맞고,
"실내를 1024 로 줄이면 얼마나 남는가"는 틀린다.

이 모듈은 그 계산을 재현 가능한 코드로 옮기고, 베이킹 단계에서
자주 손으로 맞추는 두 가지(익스플로전 오프셋, 케이지 여유)를
검증 가능한 형태로 만든다. 외부 의존성은 없다.

제공하는 것
  formats  BC1~BC7·비압축 포맷별 bpp 와 해상도별 실크기 표
  vram     차종 수·해상도·포맷·대수로 텍스처 상주량·인스턴스 버퍼·예산 비율
  packing  개별 AO/Roughness/Metallic vs ORM 한 장 — 채널 패킹 절감률
  explode  겹치는 부품을 축 방향으로 분리하는 익스플로전 베이킹 오프셋 계산
  cage     케이지(로우폴리 복제 + Alt+S)가 하이폴리를 감싸는지 검증

사용 예:
    # RTX 3080 10 GiB, 차종 18개, 외장 4096 / 실내 2048, 2,000대
    python -m pipeline.vehicle_asset_optimizer vram --chassis 18 --exterior 4096 --interior 2048

    # 포맷별 실크기 (4096 / 2048 / 1024, 밉 포함)
    python -m pipeline.vehicle_asset_optimizer formats

    # ORM 패킹 절감률
    python -m pipeline.vehicle_asset_optimizer packing --resolution 4096

    # 씬 JSON 으로 익스플로전 오프셋 계산 (Blender 스크립트가 덤프한 bbox)
    python -m pipeline.vehicle_asset_optimizer explode --json scene.json --axis z --gap 0.02

    # 케이지 검증
    python -m pipeline.vehicle_asset_optimizer cage --json cage.json

씬 JSON 형식:
    {"objects": [{"name": "seat_frame", "lo": [-0.3, -0.3, 0.20],
                                     "hi": [ 0.3,  0.3, 0.45]}, ...]}
    {"low":  {"name": "door_low",  "lo": [...], "hi": [...], "verts": 1840},
     "high": {"name": "door_high", "lo": [...], "hi": [...], "verts": 412000},
     "cage": {"name": "door_cage", "lo": [...], "hi": [...], "verts": 1840}}

    lo/hi 대신 min/max 키도 받는다. 단위는 장면 단위(블렌더 기본 = m)다.

수치의 근거와 한계는 docs/blender_asset_production_troubleshooting_guide.md
9~19장(베이킹)과 12~19장(VRAM)에 정리했다. 계산은 **계획용 근사치**이고,
최종 확정은 엔진에서 `stat streaming`·`stat rhi` 로 실측한다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

MIB = 1024 * 1024
KIB = 1024

# NVIDIA 표기 10 GB = 10 GiB = 10 * 1024 MiB (RTX 3080)
RTX3080_VRAM_MIB = 10 * 1024

# 블록 압축은 4x4 텍셀 = 1 블록. 밉 체인의 마지막 세 단(4x4/2x2/1x1)도 1블록을 쓴다.
BLOCK_EDGE = 4


class BudgetError(ValueError):
    """입력이 계산의 전제를 벗어났을 때 (해상도 0, 알 수 없는 포맷 등)."""


# --------------------------------------------------------------------------- #
# 포맷 표
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TextureFormat:
    """텍스처 압축 포맷 하나.

    ``bytes_per_block`` 이 있으면 4x4 블록 압축(BC 계열), 없으면 픽셀당
    ``bits_per_pixel`` 로 계산하는 비압축 포맷이다.
    """

    key: str
    label: str
    bits_per_pixel: float
    bytes_per_block: int | None
    usage: str

    @property
    def block_compressed(self) -> bool:
        return self.bytes_per_block is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "bits_per_pixel": self.bits_per_pixel,
            "bytes_per_block": self.bytes_per_block,
            "usage": self.usage,
        }


FORMATS: dict[str, TextureFormat] = {
    "bc1": TextureFormat("bc1", "BC1", 4.0, 8, "RGB 5:6:5 + 1bit alpha. 도색 albedo·마스크"),
    "bc3": TextureFormat("bc3", "BC3", 8.0, 16, "RGB + 8bit alpha. 유리 마스크·데칼"),
    "bc4": TextureFormat("bc4", "BC4", 4.0, 8, "단일 채널 8bit. AO·Roughness·Metallic 회색조"),
    "bc5": TextureFormat("bc5", "BC5", 8.0, 16, "2채널 8bit. 탄젠트 노멀 XY (UE NormalMap 기본)"),
    "bc6h": TextureFormat("bc6h", "BC6H", 8.0, 16, "HDR RGB. 라이트맵·발광"),
    "bc7": TextureFormat("bc7", "BC7", 8.0, 16, "RGB(A) 4~7bit. Albedo·ORM 고품질"),
    "r8": TextureFormat("r8", "R8", 8.0, None, "비압축 단일 채널 (마스크·높이)"),
    "rgba8": TextureFormat("rgba8", "RGBA8", 32.0, None, "비압축 4채널 (UI·디버그)"),
    "rgba16f": TextureFormat("rgba16f", "RGBA16F", 64.0, None, "비압축 HDR (조명 데이터)"),
}

# UE 텍스처 임포트 기본값과 맞춘 이름 (문서 21장 표)
UE_DEFAULT_FORMATS: dict[str, str] = {
    "normal": "bc5",
    "albedo": "bc7",
    "orm": "bc7",
    "ao": "bc4",
    "roughness": "bc4",
    "metallic": "bc4",
    "mask": "bc1",
}

# 차량 텍스처 세트의 기본 구성 (외장 / 실내·시트)
DEFAULT_MAP_LAYOUT: tuple[tuple[str, str], ...] = (
    ("normal", "bc5"),
    ("albedo", "bc7"),
    ("orm", "bc7"),
)


def get_format(key: str) -> TextureFormat:
    try:
        return FORMATS[key.lower()]
    except KeyError as exc:
        raise BudgetError(
            f"알 수 없는 포맷 '{key}' — 사용 가능: {', '.join(sorted(FORMATS))}"
        ) from exc


# --------------------------------------------------------------------------- #
# 크기 계산
# --------------------------------------------------------------------------- #


def _validate_resolution(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise BudgetError(f"해상도는 1 이상이어야 한다 (받은 값 {width}x{height})")


def _mip_sizes(width: int, height: int) -> list[tuple[int, int]]:
    levels = [(width, height)]
    while levels[-1][0] > 1 or levels[-1][1] > 1:
        levels.append((max(1, levels[-1][0] // 2), max(1, levels[-1][1] // 2)))
    return levels


def _level_bytes(width: int, height: int, fmt: TextureFormat) -> int:
    if fmt.bytes_per_block is not None:
        blocks_x = -(-width // BLOCK_EDGE)  # ceil
        blocks_y = -(-height // BLOCK_EDGE)
        return blocks_x * blocks_y * fmt.bytes_per_block
    return int(width * height * fmt.bits_per_pixel / 8)


def texture_bytes(
    width: int,
    height: int,
    fmt: str | TextureFormat = "bc7",
    mips: bool = True,
) -> int:
    """텍스처 한 장의 바이트. ``mips=True`` 면 밉 체인 전체를 합산한다.

    블록 압축은 밉 마지막 세 단(4x4, 2x2, 1x1)도 각각 1블록(BC1/BC4 8B,
    BC5/BC7 16B)을 차지한다. 이 3블록은 무시할 수 있는 크기지만,
    계산기를 만들 때 빼먹으면 작은 텍스처에서만 어긋나 원인을 찾기 어렵다.
    """

    spec = get_format(fmt) if isinstance(fmt, str) else fmt
    _validate_resolution(width, height)
    if not isinstance(width, int) or not isinstance(height, int):
        raise BudgetError("해상도는 정수여야 한다")

    levels = _mip_sizes(width, height) if mips else [(width, height)]
    return sum(_level_bytes(w, h, spec) for w, h in levels)


def base_texture_bytes(width: int, height: int, fmt: str | TextureFormat = "bc7") -> int:
    """베이스 밉(0단) 한 장만의 바이트."""

    return texture_bytes(width, height, fmt, mips=False)


def mip_bytes(width: int, height: int, fmt: str | TextureFormat = "bc7") -> int:
    """밉 체인이 추가로 차지하는 바이트."""

    return texture_bytes(width, height, fmt, mips=True) - texture_bytes(width, height, fmt, mips=False)


def mib(value: float) -> float:
    return value / MIB


def format_size(num_bytes: float, unit: str = "MiB") -> str:
    """1024 기준으로 KiB/MiB/GiB 를 골라 표시한다."""

    if unit == "KiB":
        return f"{num_bytes / KIB:.1f} KiB"
    if unit == "GiB":
        return f"{num_bytes / (MIB * 1024):.2f} GiB"
    return f"{num_bytes / MIB:.1f} MiB"


# --------------------------------------------------------------------------- #
# 텍스처 세트
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MapSpec:
    """텍스처 한 장의 사양. ``count`` 는 같은 해상도·포맷의 변형(도색 3종 등)."""

    name: str
    fmt: str
    width: int
    height: int
    count: int = 1

    def __post_init__(self) -> None:
        _validate_resolution(self.width, self.height)
        get_format(self.fmt)
        if self.count < 0:
            raise BudgetError(f"{self.name}: count 는 0 이상이어야 한다")

    def bytes(self, mips: bool = True) -> int:
        return texture_bytes(self.width, self.height, self.fmt, mips=mips) * self.count

    def base_bytes(self) -> int:
        return base_texture_bytes(self.width, self.height, self.fmt) * self.count

    def label(self) -> str:
        suffix = f" x{self.count}" if self.count != 1 else ""
        return f"{self.name} {self.width}x{self.height} {get_format(self.fmt).label}{suffix}"

    def as_dict(self, mips: bool = True) -> dict[str, Any]:
        return {
            "name": self.name,
            "format": self.fmt,
            "width": self.width,
            "height": self.height,
            "count": self.count,
            "bytes": self.bytes(mips),
            "mib": round(mib(self.bytes(mips)), 3),
        }


@dataclass(frozen=True)
class VehicleSet:
    """차량 한 대의 텍스처 묶음(외장 / 실내·시트 등)."""

    name: str
    maps: tuple[MapSpec, ...]

    def total_bytes(self, mips: bool = True) -> int:
        return sum(spec.bytes(mips) for spec in self.maps)

    def base_bytes(self) -> int:
        return sum(spec.base_bytes() for spec in self.maps)

    def total_mib(self, mips: bool = True) -> float:
        return mib(self.total_bytes(mips))

    def map_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.maps)

    def find(self, name: str) -> MapSpec | None:
        for spec in self.maps:
            if spec.name == name:
                return spec
        return None

    def replace(self, name: str, new: MapSpec | None) -> "VehicleSet":
        """``name`` 을 ``new`` 로 바꾼 새 세트. ``new=None`` 이면 제거한다."""

        maps: list[MapSpec] = []
        for spec in self.maps:
            if spec.name == name:
                if new is not None:
                    maps.append(new)
            else:
                maps.append(spec)
        if new is not None and name not in self.map_names():
            maps.append(new)
        return VehicleSet(self.name, tuple(maps))

    def scaled(self, factor: float, name: str | None = None) -> "VehicleSet":
        """모든 맵 해상도를 ``factor`` 배(내림, 최소 1)로 바꾼다."""

        if factor <= 0:
            raise BudgetError("배율은 0보다 커야 한다")
        maps = tuple(
            MapSpec(
                spec.name,
                spec.fmt,
                max(1, int(spec.width * factor)),
                max(1, int(spec.height * factor)),
                spec.count,
            )
            for spec in self.maps
        )
        return VehicleSet(name or f"{self.name}@{factor:g}x", maps)

    def as_dict(self, mips: bool = True) -> dict[str, Any]:
        return {
            "name": self.name,
            "total_bytes": self.total_bytes(mips),
            "total_mib": round(self.total_mib(mips), 3),
            "maps": [spec.as_dict(mips) for spec in self.maps],
        }


def default_vehicle_sets(
    exterior: int = 4096,
    interior: int = 2048,
    layout: Sequence[tuple[str, str]] = DEFAULT_MAP_LAYOUT,
) -> tuple[VehicleSet, VehicleSet]:
    """외장 3장(노멀/Albedo/ORM) + 실내 3장 기본 구성."""

    ext = VehicleSet(
        f"exterior@{exterior}",
        tuple(MapSpec(name, fmt, exterior, exterior) for name, fmt in layout),
    )
    itr = VehicleSet(
        f"interior@{interior}",
        tuple(MapSpec(name, fmt, interior, interior) for name, fmt in layout),
    )
    return ext, itr


def parse_map_specs(text: str, width: int, height: int | None = None) -> tuple[MapSpec, ...]:
    """``"normal=bc5,albedo=bc7,orm=bc7"`` 를 MapSpec 묶음으로.

    ``"normal=bc5:2"`` 처럼 콜론 뒤에 개수를 붙일 수 있다(도색 3종 등).
    """

    specs: list[MapSpec] = []
    for chunk in text.split(","):
        item = chunk.strip()
        if not item:
            continue
        if "=" not in item:
            raise BudgetError(f"맵 사양은 '이름=포맷' 형식이어야 한다 (받은 값 '{item}')")
        name, rest = item.split("=", 1)
        count = 1
        if ":" in rest:
            rest, count_text = rest.split(":", 1)
            try:
                count = int(count_text)
            except ValueError as exc:
                raise BudgetError(f"{name}: 개수는 정수여야 한다 ('{count_text}')") from exc
        specs.append(MapSpec(name.strip(), rest.strip(), width, height or width, count))
    if not specs:
        raise BudgetError("맵 사양이 비어 있다")
    return tuple(specs)


def _unpack_orm(vs: VehicleSet) -> VehicleSet:
    """ORM 한 장을 AO/Roughness/Metallic 세 장(BC4)으로 되돌린 세트."""

    orm = vs.find("orm")
    if orm is None:
        return vs
    unpacked = vs.replace("orm", None)
    for channel in ("ao", "roughness", "metallic"):
        unpacked = unpacked.replace(
            channel, MapSpec(channel, "bc4", orm.width, orm.height, orm.count)
        )
    return VehicleSet(f"{vs.name}+unpacked", unpacked.maps)


# --------------------------------------------------------------------------- #
# 함대(Flеet) 예산
# --------------------------------------------------------------------------- #


@dataclass
class FleetReport:
    chassis_count: int
    fleet_size: int
    exterior: VehicleSet
    interior: VehicleSet
    budget_mib: float
    instance_bytes: int
    mips: bool = True
    scenarios: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # --- 파생 값 --- #
    @property
    def per_model_bytes(self) -> int:
        return self.exterior.total_bytes(self.mips) + self.interior.total_bytes(self.mips)

    @property
    def per_model_mib(self) -> float:
        return mib(self.per_model_bytes)

    @property
    def station_total_bytes(self) -> int:
        """텍스처 상주량 — 차종 수에만 비례한다(대수와 무관)."""

        return self.per_model_bytes * self.chassis_count

    @property
    def station_total_mib(self) -> float:
        return mib(self.station_total_bytes)

    @property
    def instance_buffer_bytes(self) -> int:
        return self.instance_bytes * self.fleet_size

    @property
    def instance_buffer_mib(self) -> float:
        return mib(self.instance_buffer_bytes)

    @property
    def budget_ratio(self) -> float:
        return self.station_total_mib / self.budget_mib

    @property
    def headroom_mib(self) -> float:
        return self.budget_mib - self.station_total_mib

    @property
    def verdict(self) -> str:
        return budget_verdict(self.budget_ratio)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chassis_count": self.chassis_count,
            "fleet_size": self.fleet_size,
            "mips": self.mips,
            "budget_mib": self.budget_mib,
            "exterior": self.exterior.as_dict(self.mips),
            "interior": self.interior.as_dict(self.mips),
            "per_model_mib": round(self.per_model_mib, 3),
            "station_total_mib": round(self.station_total_mib, 3),
            "station_total_bytes": self.station_total_bytes,
            "instance_bytes": self.instance_bytes,
            "instance_buffer_mib": round(self.instance_buffer_mib, 4),
            "budget_ratio": round(self.budget_ratio, 5),
            "headroom_mib": round(self.headroom_mib, 3),
            "verdict": self.verdict,
            "scenarios": self.scenarios,
            "notes": self.notes,
        }


def budget_verdict(ratio: float) -> str:
    """텍스처 상주량이 VRAM 예산에서 차지하는 비율의 판정.

    차량 텍스처는 VRAM 의 **일부**일 뿐이다. 프레임버퍼·지오메트리·
    환경 텍스처·스트리밍 풀이 나머지를 쓰므로, 차량 몫은 20% 아래가
    이상적이고 35% 를 넘으면 다른 항목을 줄여야 한다.
    """

    if ratio <= 0.20:
        return "여유"
    if ratio <= 0.35:
        return "적정"
    if ratio <= 0.50:
        return "주의"
    return "초과"


def analyze_fleet(
    chassis_count: int = 18,
    fleet_size: int = 2000,
    exterior: VehicleSet | None = None,
    interior: VehicleSet | None = None,
    *,
    budget_mib: float = RTX3080_VRAM_MIB,
    instance_bytes: int = 256,
    mips: bool = True,
) -> FleetReport:
    """차종 수·대수·해상도로 텍스처 상주량과 예산 비율을 낸다."""

    if chassis_count < 1:
        raise BudgetError(f"차종 수는 1 이상이어야 한다 (받은 값 {chassis_count})")
    if fleet_size < 0:
        raise BudgetError(f"대수는 0 이상이어야 한다 (받은 값 {fleet_size})")
    if budget_mib <= 0:
        raise BudgetError(f"예산은 0보다 커야 한다 (받은 값 {budget_mib})")
    if instance_bytes < 0:
        raise BudgetError(f"인스턴스 바이트는 0 이상이어야 한다 (받은 값 {instance_bytes})")

    if exterior is None or interior is None:
        ext, itr = default_vehicle_sets()
        exterior = exterior or ext
        interior = interior or itr

    report = FleetReport(
        chassis_count=chassis_count,
        fleet_size=fleet_size,
        exterior=exterior,
        interior=interior,
        budget_mib=budget_mib,
        instance_bytes=instance_bytes,
        mips=mips,
    )
    report.scenarios = _build_scenarios(report)
    report.notes = _build_notes(report)
    return report


def _variant_total_mib(ext: VehicleSet, itr: VehicleSet, chassis: int, mips: bool) -> float:
    return mib((ext.total_bytes(mips) + itr.total_bytes(mips)) * chassis)


def _build_scenarios(report: FleetReport) -> dict[str, dict[str, float]]:
    """"줄이면 얼마나 남는가" 를 같은 단위로 나란히 둔다(양수 = 절감)."""

    base = report.station_total_mib
    out: dict[str, dict[str, float]] = {}

    for key, label, ext, itr in (
        (
            "interior_half",
            "실내 2048→1024 (디테일 노멀 타일로 대체)",
            report.exterior,
            report.interior.scaled(0.5, "interior@half"),
        ),
        (
            "exterior_half",
            "외장 4096→2048",
            report.exterior.scaled(0.5, "exterior@half"),
            report.interior,
        ),
        (
            "orm_unpacked",
            "ORM → AO/Roughness/Metallic 3장(BC4) 분리(음수 = 증가)",
            _unpack_orm(report.exterior),
            _unpack_orm(report.interior),
        ),
        (
            "both_packed",
            "외장·실내 모두 절반(최소 예산)",
            report.exterior.scaled(0.5, "exterior@half"),
            report.interior.scaled(0.5, "interior@half"),
        ),
    ):
        total = _variant_total_mib(ext, itr, report.chassis_count, report.mips)
        out[key] = {
            "label": label,  # type: ignore[dict-item]
            "station_total_mib": round(total, 1),
            "delta_mib": round(base - total, 1),
            "budget_ratio": round(total / report.budget_mib, 4),
        }
    return out


def _build_notes(report: FleetReport) -> list[str]:
    unit = "밉 체인 포함" if report.mips else "베이스 밉만"
    notes = [
        f"계산 단위: 1 MiB = 1,048,576 B, {unit}.",
        "텍스처 상주량은 차종 수에만 비례한다 — 2,000대여도 18차종이면 18세트만 메모리에 있다.",
        (
            f"인스턴스 버퍼: {report.fleet_size:,}대 x {report.instance_bytes} B "
            f"= {report.instance_buffer_mib:.2f} MiB (텍스처의 {report.instance_buffer_mib / max(report.station_total_mib, 1e-9) * 100:.2f}%)."
        ),
        (
            f"예산 {report.budget_mib:,.0f} MiB 중 차량 텍스처가 {report.station_total_mib:,.0f} MiB "
            f"= {report.budget_ratio * 100:.1f}%."
        ),
    ]
    if report.mips:
        notes.append("밉 체인은 베이스 밉의 약 33% 를 더 쓴다(4/3). 밉을 빼고 계산하면 25% 낙관적이 된다.")
    if report.per_model_mib > 0 and report.interior.total_mib(report.mips) > report.exterior.total_mib(report.mips) * 0.35:
        notes.append("실내 세트가 외장의 35% 를 넘는다 — 실내는 화면에서 멀고 어둡다. 해상도를 먼저 의심한다.")
    return notes


# --------------------------------------------------------------------------- #
# 채널 패킹 비교
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PackingReport:
    width: int
    height: int
    separate_maps: tuple[MapSpec, ...]
    packed_maps: tuple[MapSpec, ...]
    mips: bool = True

    @property
    def separate_bytes(self) -> int:
        return sum(spec.bytes(self.mips) for spec in self.separate_maps)

    @property
    def packed_bytes(self) -> int:
        return sum(spec.bytes(self.mips) for spec in self.packed_maps)

    @property
    def saving_pct(self) -> float:
        if self.separate_bytes == 0:
            return 0.0
        return 1.0 - self.packed_bytes / self.separate_bytes

    @property
    def separate_mib(self) -> float:
        return mib(self.separate_bytes)

    @property
    def packed_mib(self) -> float:
        return mib(self.packed_bytes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "mips": self.mips,
            "separate": {
                "maps": [spec.as_dict(self.mips) for spec in self.separate_maps],
                "total_mib": round(self.separate_mib, 3),
            },
            "packed": {
                "maps": [spec.as_dict(self.mips) for spec in self.packed_maps],
                "total_mib": round(self.packed_mib, 3),
            },
            "saving_pct": round(self.saving_pct * 100, 1),
        }


def packing_comparison(
    width: int = 4096,
    height: int | None = None,
    *,
    separate_fmt: str = "bc7",
    packed_fmt: str = "bc7",
    mips: bool = True,
) -> PackingReport:
    """AO·Roughness·Metallic 를 따로 저장할 때 vs ORM 한 장.

    절감률은 **같은 포맷으로 저장했다는 가정**에서 나온다. 세 장을 각각
    BC7(8bpp)로 저장하면 3 -> 1 이므로 66.7%, 회색조를 BC4(4bpp)로
    제대로 골라 저장했다면 33.3% 다. 어느 쪽이든 하나의 텍스처 샘플러와
    하나의 스트리밍 단위로 줄어드는 효과가 더 크다.
    """

    height = height or width
    separate = tuple(
        MapSpec(name, separate_fmt, width, height) for name in ("ao", "roughness", "metallic")
    )
    packed = (MapSpec("orm", packed_fmt, width, height),)
    return PackingReport(width, height, separate, packed, mips)


# --------------------------------------------------------------------------- #
# 익스플로전 베이킹
# --------------------------------------------------------------------------- #

AXIS_INDEX: dict[str, int] = {"x": 0, "y": 1, "z": 2}
UNIT_SCALE: dict[str, float] = {"m": 1.0, "cm": 100.0, "mm": 1000.0}


def _as_vec3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BudgetError(f"{label}: 길이 3의 좌표 목록이어야 한다 (받은 값 {value!r})")
    try:
        return tuple(float(v) for v in value)  # type: ignore[return-value]
    except (TypeError, ValueError) as exc:
        raise BudgetError(f"{label}: 숫자가 아닌 값이 있다 ({value!r})") from exc


@dataclass(frozen=True)
class PartBox:
    """부품 하나의 축 정렬 경계 상자(장면 단위)."""

    name: str
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]

    def __post_init__(self) -> None:
        for axis, (low, high) in zip("xyz", zip(self.lo, self.hi)):
            if high < low:
                raise BudgetError(f"{self.name}: {axis} 축에서 hi({high}) < lo({low})")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PartBox":
        name = str(data.get("name") or "unnamed")
        lo = _as_vec3(data.get("lo", data.get("min")), f"{name}.lo")
        hi = _as_vec3(data.get("hi", data.get("max")), f"{name}.hi")
        return cls(name, lo, hi)

    def size(self, axis: str) -> float:
        idx = AXIS_INDEX[axis]
        return self.hi[idx] - self.lo[idx]

    def center(self, axis: str) -> float:
        idx = AXIS_INDEX[axis]
        return (self.hi[idx] + self.lo[idx]) / 2.0

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "lo": list(self.lo), "hi": list(self.hi)}


@dataclass(frozen=True)
class ExplosionEntry:
    name: str
    group: int
    offset: tuple[float, float, float]
    lo: float
    hi: float
    new_lo: float
    new_hi: float

    def as_dict(self, unit: str = "m") -> dict[str, Any]:
        scale = UNIT_SCALE[unit]
        return {
            "name": self.name,
            "group": self.group,
            "offset": [round(v * scale, 6) for v in self.offset],
            "distance": round(abs(self.new_lo - self.lo) * scale, 6),
            "span": [round(self.new_lo * scale, 6), round(self.new_hi * scale, 6)],
            "unit": unit,
        }


@dataclass
class ExplosionPlan:
    axis: str
    gap: float
    entries: tuple[ExplosionEntry, ...]
    groups: int

    @property
    def max_distance(self) -> float:
        return max((abs(e.new_lo - e.lo) for e in self.entries), default=0.0)

    @property
    def displaced(self) -> int:
        return sum(1 for e in self.entries if abs(e.new_lo - e.lo) > 1e-9)

    def overlaps(self, tolerance: float = 1e-9) -> list[tuple[str, str]]:
        """분리 후에도 축 투영이 겹치는 쌍. 비어 있어야 정상이다."""

        found: list[tuple[str, str]] = []
        ordered = sorted(self.entries, key=lambda e: (e.new_lo, e.new_hi))
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if b.new_lo >= a.new_hi - tolerance:
                    break
                if a.new_lo < b.new_hi - tolerance and b.new_lo < a.new_hi - tolerance:
                    found.append((a.name, b.name))
        return found

    def as_dict(self, unit: str = "m") -> dict[str, Any]:
        return {
            "axis": self.axis,
            "gap": self.gap,
            "unit": unit,
            "groups": self.groups,
            "displaced": self.displaced,
            "max_distance": round(self.max_distance * UNIT_SCALE[unit], 6),
            "residual_overlaps": self.overlaps(),
            "entries": [e.as_dict(unit) for e in self.entries],
        }


def plan_explosion(
    parts: Sequence[PartBox],
    axis: str = "z",
    gap: float = 0.0,
) -> ExplosionPlan:
    """겹치는 부품을 ``axis`` 방향으로 밀어 축 투영을 서로 떼어 놓는다.

    원리: 축에 투영한 구간이 서로 겹치는 부품은 같은 그룹으로 묶고,
    그룹 안에서 원래 순서대로 ``gap`` 만큼 띄워 다시 쌓는다. 그룹의 첫
    부품은 제자리에 두므로 이동 거리가 최소가 되고, 서로 겹치지 않던
    부품(다른 그룹)은 건드리지 않는다.

    오브젝트 **원점은 건드리지 않는다** — 오프셋만 계산해 돌려주므로
    호출하는 쪽이 위치를 더했다가 빼면 된다(문서 9.4절 복원 규칙).
    """

    if axis not in AXIS_INDEX:
        raise BudgetError(f"축은 x/y/z 중 하나여야 한다 (받은 값 '{axis}')")
    if gap < 0:
        raise BudgetError(f"간격은 0 이상이어야 한다 (받은 값 {gap})")
    if not parts:
        return ExplosionPlan(axis, gap, (), 0)

    idx = AXIS_INDEX[axis]
    ordered = sorted(parts, key=lambda p: (p.lo[idx], p.hi[idx], p.name))

    # 1) 축 투영이 겹치는 부품을 그룹으로 묶는다 (닿기만 해도 같은 그룹).
    groups: list[list[PartBox]] = []
    group_hi = -math.inf
    for part in ordered:
        if groups and part.lo[idx] <= group_hi + 1e-9:
            groups[-1].append(part)
            group_hi = max(group_hi, part.hi[idx])
        else:
            groups.append([part])
            group_hi = part.hi[idx]

    # 2) 그룹 안에서 다시 쌓는다.
    entries: list[ExplosionEntry] = []
    for group_id, members in enumerate(groups):
        cursor = members[0].lo[idx]
        for part in members:
            thickness = part.hi[idx] - part.lo[idx]
            offset = cursor - part.lo[idx]
            vec = [0.0, 0.0, 0.0]
            vec[idx] = offset
            entries.append(
                ExplosionEntry(
                    name=part.name,
                    group=group_id,
                    offset=(vec[0], vec[1], vec[2]),
                    lo=part.lo[idx],
                    hi=part.hi[idx],
                    new_lo=cursor,
                    new_hi=cursor + thickness,
                )
            )
            cursor += thickness + gap

    return ExplosionPlan(axis, gap, tuple(entries), len(groups))


# --------------------------------------------------------------------------- #
# 케이지 검증
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MeshProbe:
    """베이킹에 참여하는 메시 하나의 요약(경계 상자 + 버텍스 수)."""

    name: str
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    verts: int

    def __post_init__(self) -> None:
        if self.verts < 0:
            raise BudgetError(f"{self.name}: verts 는 0 이상이어야 한다")
        PartBox(self.name, self.lo, self.hi)  # lo/hi 검증 재사용

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeshProbe":
        name = str(data.get("name") or "unnamed")
        lo = _as_vec3(data.get("lo", data.get("min")), f"{name}.lo")
        hi = _as_vec3(data.get("hi", data.get("max")), f"{name}.hi")
        try:
            verts = int(data.get("verts", data.get("vertices", 0)))
        except (TypeError, ValueError) as exc:
            raise BudgetError(f"{name}.verts: 정수여야 한다") from exc
        return cls(name, lo, hi, verts)

    def size(self, axis: str) -> float:
        idx = AXIS_INDEX[axis]
        return self.hi[idx] - self.lo[idx]

    def contains(self, other: "MeshProbe", margin: float = 0.0) -> bool:
        return all(
            self.lo[i] <= other.lo[i] - margin and self.hi[i] >= other.hi[i] + margin
            for i in range(3)
        )

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "lo": list(self.lo), "hi": list(self.hi), "verts": self.verts}


@dataclass(frozen=True)
class Check:
    key: str
    status: str  # OK / WARN / FAIL / INFO
    value: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "status": self.status, "value": self.value, "detail": self.detail}


@dataclass(frozen=True)
class CageReport:
    low: MeshProbe
    high: MeshProbe
    cage: MeshProbe
    checks: tuple[Check, ...]
    margins: tuple[float, float, float]

    @property
    def failed(self) -> bool:
        return any(c.status == "FAIL" for c in self.checks)

    @property
    def warned(self) -> bool:
        return any(c.status == "WARN" for c in self.checks)

    @property
    def verdict(self) -> str:
        if self.failed:
            return "FAIL"
        if self.warned:
            return "WARN"
        return "OK"

    @property
    def min_margin(self) -> float:
        return min(self.margins)

    @property
    def exposed_axes(self) -> tuple[str, ...]:
        return tuple(a for a, m in zip("xyz", self.margins) if m < 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "low": self.low.as_dict(),
            "high": self.high.as_dict(),
            "cage": self.cage.as_dict(),
            "margins": [round(m, 6) for m in self.margins],
            "verdict": self.verdict,
            "checks": [c.as_dict() for c in self.checks],
        }


def validate_cage(
    low: MeshProbe,
    high: MeshProbe,
    cage: MeshProbe,
    *,
    min_margin_ratio: float = 0.004,
    max_margin_ratio: float = 0.35,
) -> CageReport:
    """케이지가 "로우폴리 복제 + 바깥으로 부풀린" 상태인지 검사한다.

    케이지의 실패는 대개 두 방향이다.
      - 너무 붙었다: 광선이 하이폴리를 놓쳐 노멀맵에 구멍(검은 점)이 생긴다.
      - 너무 멀었다: 옆 부품·반대편 면을 먼저 맞아 탄젠트가 꼬이고,
        베이크 시간이 늘고, 곡면이 밀려 보인다.
    경계 상자만으로도 이 두 극단과 토폴로지 불일치는 잡힌다.
    """

    if min_margin_ratio < 0:
        raise BudgetError("min_margin_ratio 는 0 이상이어야 한다")
    if max_margin_ratio <= min_margin_ratio:
        raise BudgetError("max_margin_ratio 는 min_margin_ratio 보다 커야 한다")

    checks: list[Check] = []

    # 1) 토폴로지: 케이지는 LP 의 복제본이어야 한다.
    if low.verts <= 0:
        checks.append(Check("topology", "INFO", f"low {low.verts}", "로우폴리 버텍스 수가 없다 — 토폴로지 비교 생략"))
    elif cage.verts == low.verts:
        checks.append(Check("topology", "OK", f"{cage.verts} = low {low.verts}", "케이지가 로우폴리와 같은 버텍스 수다"))
    else:
        checks.append(
            Check(
                "topology",
                "FAIL",
                f"cage {cage.verts} != low {low.verts}",
                "케이지는 로우폴리를 복제해 Alt+S 로 부풀린 같은 메시여야 한다(면 수·순서 일치)",
            )
        )

    # 2) 케이지가 하이폴리를 감싸는가 + 축별 여유
    margins: list[float] = []
    for axis in "xyz":
        idx = AXIS_INDEX[axis]
        span = max(high.size(axis), 1e-9)
        # 케이지가 하이폴리보다 바깥으로 나온 양 (음수 = 하이폴리가 밖으로 삐져나옴)
        margin = min(high.lo[idx] - cage.lo[idx], cage.hi[idx] - high.hi[idx])
        margins.append(margin / span)
    ratio = min(margins)

    if ratio < 0:
        bad = [a for a, m in zip("xyz", margins) if m < 0]
        checks.append(
            Check(
                "covers_high",
                "FAIL",
                f"{ratio * 100:+.1f}%",
                f"{'/'.join(bad)} 축에서 하이폴리가 케이지 밖으로 나온다 — 그 면은 광선이 아예 닿지 않는다",
            )
        )
    else:
        checks.append(Check("covers_high", "OK", f"{ratio * 100:+.1f}%", "케이지가 하이폴리를 모든 축에서 감싼다"))

    if ratio < 0:
        checks.append(
            Check(
                "margin",
                "INFO",
                f"{ratio * 100:+.2f}%",
                "케이지가 하이폴리를 감싸지 못해 여유를 평가하지 않는다 (covers_high 참조)",
            )
        )
    elif ratio < min_margin_ratio:
        checks.append(
            Check(
                "margin",
                "WARN",
                f"{ratio * 100:.2f}% (< {min_margin_ratio * 100:.2f}%)",
                "여유가 하이폴리 크기의 0.4% 미만 — 오목 모서리에서 광선을 놓친다. Alt+S 로 한 번 더",
            )
        )
    elif ratio > max_margin_ratio:
        checks.append(
            Check(
                "margin",
                "WARN",
                f"{ratio * 100:.1f}% (> {max_margin_ratio * 100:.0f}%)",
                "케이지가 과대 — 옆 부품·반대편을 먼저 맞고 베이크가 느려진다. 부푼 양을 줄인다",
            )
        )
    else:
        checks.append(Check("margin", "OK", f"{ratio * 100:.2f}%", "케이지 여유가 권장 범위 안이다"))

    # 3) 케이지가 로우폴리 바깥에 있는가
    if all(cage.lo[i] <= low.lo[i] + 1e-9 and cage.hi[i] >= low.hi[i] - 1e-9 for i in range(3)):
        checks.append(Check("outside_low", "OK", "모든 축", "케이지가 로우폴리 바깥에 있다"))
    else:
        inside = [a for i, a in enumerate("xyz") if cage.lo[i] > low.lo[i] + 1e-9 or cage.hi[i] < low.hi[i] - 1e-9]
        checks.append(
            Check(
                "outside_low",
                "WARN",
                "/".join(inside),
                "케이지가 로우폴리보다 작아지는 축이 있다 — 케이지가 안쪽으로 들어가면 광선이 뒤집힌다",
            )
        )

    # 4) 하이폴리가 로우폴리 실루엣을 벗어나는가 (정상적인 노멀 베이크의 전제)
    if all(high.lo[i] >= low.lo[i] - 1e-9 and high.hi[i] <= low.hi[i] + 1e-9 for i in range(3)):
        checks.append(
            Check(
                "silhouette",
                "WARN",
                "high ⊂ low",
                "하이폴리가 로우폴리 안에 완전히 들어간다 — 실루엣이 부풀고 법선 방향이 반대로 구워질 수 있다",
            )
        )
    else:
        checks.append(Check("silhouette", "OK", "high ⊄ low", "하이폴리가 실루엣에서 로우폴리를 벗어난다"))

    return CageReport(low, high, cage, tuple(checks), (margins[0], margins[1], margins[2]))


def cavity_risk(low: MeshProbe, high: MeshProbe, cage: MeshProbe, *, margin_ratio: float = 0.004) -> list[str]:
    """케이지가 다른 부품 사이 좁은 틈(홈·그릴·창틀)을 메울 위험을 경고한다.

    경계 상자만으로는 실제 교차를 알 수 없으므로 힌트만 낸다:
    부풀린 양이 하이폴리 대비 얇은 축 두께를 넘으면 좁은 틈이 막힌다.
    """

    hints: list[str] = []
    for axis in "xyz":
        idx = AXIS_INDEX[axis]
        balloon = (cage.hi[idx] - cage.lo[idx] - (low.hi[idx] - low.lo[idx])) / 2.0
        thickness = high.size(axis)
        if thickness > 0 and balloon > thickness * margin_ratio * 10:
            hints.append(
                f"{axis} 축: 부푼 양 {balloon:.4f} 이 하이폴리 두께 {thickness:.4f} 의 4% 를 넘는다 — 좁은 틈이 메워질 수 있다"
            )
    return hints


# --------------------------------------------------------------------------- #
# 출력 (텍스트)
# --------------------------------------------------------------------------- #


def format_formats() -> str:
    lines = ["BC 포맷 실크기 (1 MiB = 1,048,576 B, 밉 체인 포함)", ""]
    header = f"{'포맷':<6}{'bpp':>5}   " + "".join(f"{f'{r}²':>12}" for r in (4096, 2048, 1024)) + f"   {'용도':<40}"
    lines.append(header)
    lines.append("-" * len(header))
    for key in ("bc1", "bc4", "bc5", "bc7", "bc6h", "bc3", "r8", "rgba8"):
        fmt = FORMATS[key]
        cells = []
        for res in (4096, 2048, 1024):
            cells.append(f"{mib(texture_bytes(res, res, key)):>10.2f} MiB")
        lines.append(f"{fmt.label:<6}{fmt.bits_per_pixel:>5.0f}   " + "".join(cells) + f"   {fmt.usage:<40}")
    lines.append("")
    lines.append("베이스 밉만 계산하면 BC7 4096 은 16.00 MiB, 밉 포함 21.33 MiB 다(4/3).")
    return "\n".join(lines)


def format_fleet(report: FleetReport) -> str:
    unit = "밉 포함" if report.mips else "베이스 밉만"
    lines: list[str] = []
    lines.append(
        f"차량 텍스처 VRAM 예산 — 예산 {report.budget_mib:,.0f} MiB, 차종 {report.chassis_count}개, "
        f"{report.fleet_size:,}대 ({unit})"
    )
    lines.append("")
    for vs in (report.exterior, report.interior):
        lines.append(f"[{vs.name}] {len(vs.maps)}장")
        for spec in vs.maps:
            total = spec.bytes(report.mips)
            base = spec.base_bytes()
            lines.append(
                f"  {spec.label():<38}{mib(base):>7.2f} + 밉 {mib(total - base):>5.2f} = {mib(total):>7.2f} MiB"
            )
        lines.append(f"  {'합계':<38}{'':>7}{'':>9}{vs.total_mib(report.mips):>7.2f} MiB")
        lines.append("")
    lines.append(f"차종당 합계 {report.per_model_mib:8.2f} MiB  x{report.chassis_count} = {report.station_total_mib:,.1f} MiB")
    lines.append(
        f"  예산 대비 {report.budget_ratio * 100:5.1f}%  |  남는 양 {report.headroom_mib:,.1f} MiB  |  판정 {report.verdict}"
    )
    lines.append(
        f"인스턴스 버퍼 {report.fleet_size:,} x {report.instance_bytes} B = {report.instance_buffer_mib:.2f} MiB"
    )
    if report.scenarios:
        lines.append("")
        lines.append("절감 시나리오 (양수 = 줄어드는 양)")
        for key, s in report.scenarios.items():
            lines.append(
                f"  {s['label']:<40}{s['station_total_mib']:>9,.1f} MiB  "
                f"({s['delta_mib']:+,.1f} MiB, {s['budget_ratio'] * 100:5.1f}%)"
            )
    if report.notes:
        lines.append("")
        for note in report.notes:
            lines.append(f"  · {note}")
    return "\n".join(lines)


def format_packing(report: PackingReport) -> str:
    lines = [f"채널 패킹 비교 — {report.width}x{report.height}"]
    lines.append("")
    for spec in report.separate_maps:
        lines.append(f"  분리  {spec.label():<34}{mib(spec.bytes(report.mips)):>7.2f} MiB")
    lines.append(f"  분리 합계{'':<28}{report.separate_mib:>7.2f} MiB")
    lines.append("")
    for spec in report.packed_maps:
        lines.append(f"  패킹  {spec.label():<34}{mib(spec.bytes(report.mips)):>7.2f} MiB")
    lines.append(f"  패킹 합계{'':<28}{report.packed_mib:>7.2f} MiB")
    lines.append("")
    lines.append(f"  절감 {report.saving_pct * 100:.1f}%  ({report.separate_mib - report.packed_mib:.2f} MiB 절약)")
    return "\n".join(lines)


def format_explosion(plan: ExplosionPlan, unit: str = "m") -> str:
    scale = UNIT_SCALE[unit]
    lines = [f"익스플로전 베이킹 오프셋 — {plan.axis} 축, 간격 {plan.gap * scale:g} {unit}, 그룹 {plan.groups}"]
    lines.append("")
    header = f"{'부품':<28}{'그룹':>5}{'원래 구간':>22}{'이동 후':>22}{'이동':>12}"
    lines.append(header)
    lines.append("-" * len(header))
    for entry in sorted(plan.entries, key=lambda e: (e.group, e.new_lo)):
        lines.append(
            f"{entry.name:<28}{entry.group:>5}"
            f"{f'{entry.lo * scale:.3f} ~ {entry.hi * scale:.3f}':>22}"
            f"{f'{entry.new_lo * scale:.3f} ~ {entry.new_hi * scale:.3f}':>22}"
            f"{abs(entry.new_lo - entry.lo) * scale:>11.3f}"
        )
    lines.append("")
    residual = plan.overlaps()
    lines.append(
        f"  이동한 부품 {plan.displaced}/{len(plan.entries)}  |  최대 이동 {plan.max_distance * scale:.3f} {unit}"
        f"  |  잔여 겹침 {len(residual)}쌍"
    )
    if residual:
        for a, b in residual:
            lines.append(f"    [FAIL] {a} ~ {b} 가 아직 겹친다 — 간격을 늘리거나 축을 바꾼다")
    else:
        lines.append("    [OK  ] 축 투영이 모두 분리됐다 — 이 상태로 베이크하고 원래 위치로 되돌린다")
    return "\n".join(lines)


def format_cage(report: CageReport, unit: str = "m") -> str:
    scale = UNIT_SCALE[unit]
    lines = [
        f"케이지 검증 — {report.verdict}",
        f"  low  {report.low.name:<20} {report.low.verts:>7} verts",
        f"  high {report.high.name:<20} {report.high.verts:>7} verts",
        f"  cage {report.cage.name:<20} {report.cage.verts:>7} verts",
        "",
    ]
    for check in report.checks:
        tag = {"OK": "[OK  ]", "WARN": "[WARN]", "FAIL": "[FAIL]", "INFO": "[info]"}[check.status]
        lines.append(f"  {tag} {check.value:<22} {check.detail}")
    lines.append("")
    lines.append(
        "  축별 여유 " + "  ".join(f"{a}:{m * 100:+.2f}%" for a, m in zip("xyz", report.margins))
    )
    return "\n".join(lines)


def format_checklist() -> str:
    """12단계 익스포트/베이크 체크리스트 (문서 20장과 같은 순서)."""

    steps = [
        ("LP 생성", "IsLowPoly 스위치로 클러스터별 LP 모드를 호출하고 예산(삼각형) 이내인지 확인"),
        ("실루엣 비교", "LP·HP 실루엣 오차를 3면(정면·측면·후면)에서 측정, 5 mm 초과 구간만 리토폴로지"),
        ("법선 전송", "Data Transfer 로 HP 커스텀 노멀을 LP 에 전송(베이킹 **전**), 4.1+ 는 auto smooth 불필요"),
        ("UV", "클러스터당 1 UV 세트(0~1), 라이트맵 없음, 패딩 8px(4096) / 4px(2048)"),
        ("법선 확인", "LP 하드 엣지가 HP 패널 라인과 일치하는지, 뒤집힌 면이 없는지"),
        ("익스플로전", "겹치는 클러스터를 축으로 분리(explode), 원래 행렬 저장"),
        ("케이지", "LP 복제 + Alt+S(Offset Even), 여유 0.4~35%, verts 동일(cage)"),
        ("베이킹", "Cycles Normal(탄젠트, G=-Y) + AO + ORM 3채널, 512~1024 샘플 + 디노이즈"),
        ("검증", "검은 점·초록 픽셀·그라디언트 끊김을 4K 1:1 로 확인"),
        ("복원", "오프셋 0 복원, 오브젝트 원점·스케일 원상복구(적용 금지 상태 유지)"),
        ("삼각화", "Triangulate(Keep Custom Normals) 후 삼각형 수·법선 재확인"),
        ("익스포트", "FBX 3c 건너뛰기: Color 미전송 / Recompute Normals 끔 / Tangent Space 재계산 끔"),
    ]
    lines = ["블렌더 베이크·익스포트 12단계 체크리스트", ""]
    for i, (title, detail) in enumerate(steps, 1):
        lines.append(f"{i:>2}. {title:<10} {detail}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.vehicle_asset_optimizer",
        description="차량 에셋 VRAM 예산 계산기 + 익스플로전/케이지 검증기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  %(prog)s vram --chassis 18 --exterior 4096 --interior 2048\n"
            "  %(prog)s formats\n"
            "  %(prog)s packing --resolution 4096 --separate-fmt bc7\n"
            "  %(prog)s explode --json scene.json --axis z --gap 0.02\n"
            "  %(prog)s cage --json cage.json\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("formats", help="BC 포맷별 실크기 표")
    _add_common(p)

    p = sub.add_parser("vram", help="차종·해상도·대수로 텍스처 상주량과 예산 비율")
    p.add_argument("--chassis", type=int, default=18, help="차종 수 (기본 18)")
    p.add_argument("--fleet", type=int, default=2000, help="동시에 배치되는 차량 수 (기본 2000)")
    p.add_argument("--exterior", type=int, default=4096, help="외장 해상도 (기본 4096)")
    p.add_argument("--interior", type=int, default=2048, help="실내·시트 해상도 (기본 2048)")
    p.add_argument("--exterior-maps", type=str, default="normal=bc5,albedo=bc7,orm=bc7", help="외장 맵 사양")
    p.add_argument("--interior-maps", type=str, default="normal=bc5,albedo=bc7,orm=bc7", help="실내 맵 사양")
    p.add_argument("--budget-mib", type=float, default=float(RTX3080_VRAM_MIB), help="VRAM 예산 MiB (기본 10240)")
    p.add_argument("--instance-bytes", type=int, default=256, help="인스턴스당 바이트 (기본 256)")
    p.add_argument("--no-mips", action="store_true", help="베이스 밉만 계산")
    _add_common(p)

    p = sub.add_parser("packing", help="개별 맵 vs ORM 채널 패킹 비교")
    p.add_argument("--resolution", type=int, default=4096, help="해상도 (기본 4096)")
    p.add_argument("--separate-fmt", default="bc7", help="분리 저장 시 포맷 (기본 bc7)")
    p.add_argument("--packed-fmt", default="bc7", help="ORM 포맷 (기본 bc7)")
    p.add_argument("--no-mips", action="store_true", help="베이스 밉만 계산")
    _add_common(p)

    p = sub.add_parser("explode", help="익스플로전 베이킹 오프셋 계산")
    p.add_argument("--json", dest="json_in", type=str, help="씬 JSON 경로 (objects[]: name/lo/hi)")
    p.add_argument("--axis", choices=sorted(AXIS_INDEX), default="z", help="분리 축 (기본 z)")
    p.add_argument("--gap", type=float, default=0.0, help="분리 간격, 장면 단위 (기본 0)")
    p.add_argument("--unit", choices=sorted(UNIT_SCALE), default="m", help="출력 단위 (기본 m)")
    p.add_argument("--dump-json", action="store_true", help="결과를 JSON 으로 출력")
    p.add_argument("--demo", action="store_true", help="시트 클러스터 예시로 실행")

    p = sub.add_parser("cage", help="케이지 검증")
    p.add_argument("--json", dest="json_in", type=str, help="low/high/cage JSON 경로")
    p.add_argument("--min-margin", type=float, default=0.004, help="최소 여유 비율 (기본 0.004)")
    p.add_argument("--max-margin", type=float, default=0.35, help="최대 여유 비율 (기본 0.35)")
    p.add_argument("--unit", choices=sorted(UNIT_SCALE), default="m", help="출력 단위 (기본 m)")
    p.add_argument("--dump-json", action="store_true", help="결과를 JSON 으로 출력")
    p.add_argument("--demo", action="store_true", help="좋은 케이지와 나쁜 케이지를 함께 실행")

    sub.add_parser("checklist", help="12단계 익스포트/베이크 체크리스트")

    return parser


DEMO_PARTS: tuple[PartBox, ...] = (
    PartBox("seat_frame", (-0.30, -0.28, 0.20), (0.30, 0.28, 0.36)),
    PartBox("seat_cushion", (-0.29, -0.26, 0.28), (0.29, 0.26, 0.44)),
    PartBox("backrest", (-0.29, 0.20, 0.34), (0.29, 0.34, 0.90)),
    PartBox("belt_buckle", (-0.05, 0.18, 0.30), (0.05, 0.26, 0.42)),
    PartBox("headrest", (-0.14, 0.22, 0.86), (0.14, 0.34, 1.06)),
)

DEMO_LOW = MeshProbe("door_low", (-0.60, 0.00, 0.10), (0.60, 0.08, 0.70), 1840)
DEMO_HIGH = MeshProbe("door_high", (-0.60, -0.01, 0.10), (0.60, 0.10, 0.70), 412_000)
DEMO_CAGE_GOOD = MeshProbe("door_cage", (-0.612, -0.018, 0.092), (0.612, 0.116, 0.708), 1840)
DEMO_CAGE_TIGHT = MeshProbe("door_cage_tight", (-0.6006, -0.0106, 0.0994), (0.6006, 0.1006, 0.7006), 1840)
DEMO_CAGE_BAD = MeshProbe("door_cage_bad", (-0.60, 0.00, 0.10), (0.60, 0.05, 0.70), 1862)


def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise BudgetError(f"파일을 찾을 수 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BudgetError(f"JSON 파싱 실패: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise BudgetError("최상위는 객체여야 한다")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "formats":
            if args.json:
                print(json.dumps(
                    {k: {**FORMATS[k].as_dict(),
                         "mib": {str(r): round(mib(texture_bytes(r, r, k)), 2) for r in (4096, 2048, 1024)}}
                     for k in FORMATS},
                    ensure_ascii=False, indent=2))
            else:
                print(format_formats())
            return 0

        if args.command == "vram":
            exterior = VehicleSet(
                f"exterior@{args.exterior}", parse_map_specs(args.exterior_maps, args.exterior)
            )
            interior = VehicleSet(
                f"interior@{args.interior}", parse_map_specs(args.interior_maps, args.interior)
            )
            report = analyze_fleet(
                chassis_count=args.chassis,
                fleet_size=args.fleet,
                exterior=exterior,
                interior=interior,
                budget_mib=args.budget_mib,
                instance_bytes=args.instance_bytes,
                mips=not args.no_mips,
            )
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else format_fleet(report))
            return 0

        if args.command == "packing":
            report = packing_comparison(
                args.resolution,
                separate_fmt=args.separate_fmt,
                packed_fmt=args.packed_fmt,
                mips=not args.no_mips,
            )
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else format_packing(report))
            return 0

        if args.command == "explode":
            if args.demo:
                parts = list(DEMO_PARTS)
            elif args.json_in:
                data = _load_json(args.json_in)
                raw = data.get("objects")
                if not isinstance(raw, list) or not raw:
                    raise BudgetError("objects 배열이 필요하다")
                parts = [PartBox.from_dict(item) for item in raw]
            else:
                parser.error("explode 는 --json 또는 --demo 가 필요하다")
                return 2
            plan = plan_explosion(parts, axis=args.axis, gap=args.gap)
            print(
                json.dumps(plan.as_dict(args.unit), ensure_ascii=False, indent=2)
                if args.dump_json
                else format_explosion(plan, args.unit)
            )
            return 0 if not plan.overlaps() else 1

        if args.command == "cage":
            if args.demo:
                probes = (DEMO_LOW, DEMO_HIGH, DEMO_CAGE_GOOD)
                print(format_cage(validate_cage(probes[0], probes[1], probes[2],
                                                min_margin_ratio=args.min_margin,
                                                max_margin_ratio=args.max_margin), args.unit))
                for cage in (DEMO_CAGE_TIGHT, DEMO_CAGE_BAD):
                    print()
                    print(format_cage(validate_cage(DEMO_LOW, DEMO_HIGH, cage,
                                                    min_margin_ratio=args.min_margin,
                                                    max_margin_ratio=args.max_margin), args.unit))
                return 0
            if args.json_in:
                data = _load_json(args.json_in)
                missing = [k for k in ("low", "high", "cage") if k not in data]
                if missing:
                    raise BudgetError(f"low/high/cage 가 모두 필요하다 (없는 키: {', '.join(missing)})")
                report = validate_cage(
                    MeshProbe.from_dict(data["low"]),
                    MeshProbe.from_dict(data["high"]),
                    MeshProbe.from_dict(data["cage"]),
                    min_margin_ratio=args.min_margin,
                    max_margin_ratio=args.max_margin,
                )
                print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
                      if args.dump_json else format_cage(report, args.unit))
                return 0 if report.verdict != "FAIL" else 1
            parser.error("cage 는 --json 또는 --demo 가 필요하다")
            return 2

        if args.command == "checklist":
            print(format_checklist())
            return 0

        parser.error("unknown command")
        return 2

    except BudgetError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
