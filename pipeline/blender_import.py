#!/usr/bin/env python3
"""블렌더(Blender 3.6 LTS / 4.x / 5.x)에서 AI 생성 3D 에셋을 받아
PBR 머티리얼을 구성하고, 리토폴로지·폴리곤 감면·UV·Cycles 베이킹을 거쳐
게임 엔진용 로우폴리 에셋으로 내보내는 도우미.

이 파일은 일반 파이썬이 아니라 **블렌더의 파이썬 환경**에서 실행한다.

경로 A — UE5 Nanite 정적 프랍 (배경/소품, 감면 불필요)
    blender --background --factory-startup --python pipeline/blender_import.py -- \
        --model output/chair/model.glb \
        --textures output/chair/textures \
        --scale-target 1.2 \
        --blend output/chair/chair.blend

경로 B — 캐릭터/리깅/애니메이션, 모바일, 비-Nanite (감면 + 베이킹 필수)
    blender --background --factory-startup --python pipeline/blender_import.py -- \
        --model output/hero/model.glb \
        --target-tris 30000 \
        --bake normal,ao,roughness,basecolor \
        --bake-size 2048 \
        --export-fbx output/hero/hero_low.fbx \
        --blend output/hero/hero.blend

    # 5,000 / 10,000 / 30,000 처럼 목표 삼각형 수를 직접 준다.
    # --target-tris 를 주면 하이폴리 원본을 보존한 채 로우폴리 사본을 만들어
    # 그 사본을 감면 -> UV -> 케이지 -> 베이킹 -> 최종 머티리얼 구성까지 자동으로 한다.

    # GUI: Scripting 탭에 붙여넣고 아래 SETTINGS를 고친 뒤 Run Script

하는 일
  1) GLB/glTF/FBX 임포트 + 메시 검사(삼각형/버텍스/비매니폴드/UV/머티리얼)
  2) 정리: 중복 버텍스 병합, 노멀 재계산, 스무스 셰이딩(각도 기준)
     - 4.1+ : Mesh.set_sharp_from_angle (Shade Auto Smooth가 백그라운드에서 실패하는 경우 회피)
     - 3.x~4.0 : mesh.use_auto_smooth + auto_smooth_angle
  3) 스케일/원점 정리 (--scale-target, --origin)
  4) 머티리얼 노드 자동 구성 (임포트한 텍스처 세트 기준)
       BaseColor(sRGB)                  -> Principled Base Color
       Normal(Non-Color) + Normal Map   -> Principled Normal
       ORM(Non-Color) --Separate Color--> R=AO(곱연산) / G=Roughness / B=Metallic
       개별 roughness/metallic/occlusion 이 있으면 해당 채널만 덮어쓴다.
  5) 경로 B: 하이폴리 보존 + 로우폴리 사본 생성 -> 목표 삼각형 수로 감면
       Decimate(Collapse, 대칭 옵션) / Quadriflow / Voxel Remesh
  6) 경로 B: 로우폴리 UV(Smart UV Project 폴백) + 베이킹 케이지 생성
  7) 경로 B: Cycles 하이폴리->로우폴리 베이킹
       normal(탄젠트), ao, roughness, basecolor(DIFFUSE/COLOR), metallic(EMIT 트릭)
  8) 경로 B: 베이킹 결과로 로우폴리 최종 머티리얼 재구성
  9) (선택) FBX / glTF 익스포트, .blend 저장, JSON 리포트

의사결정: 폴리곤을 줄여야 하는가?
  경로 A (UE5 Nanite 정적 프랍: 배경, 소품, 건축 요소)
      -> 감면하지 않는다. 원본 고밀도 메시를 Nanite로 그대로 넣는다.
         Nanite는 폴리곤 수가 성능에 거의 영향을 주지 않는다.
  경로 B (캐릭터/스키닝, 모바일, 유니티·비-Nanite, LOD, 콜리전)
      -> 리토폴로지 + 저폴리 + 노멀/AO/러프니스 베이킹이 필수다.
         캐릭터는 Decimate만으로는 관절 루프가 무너지므로 Quadriflow/수동 리토폴로지 후
         Decimate로 마무리하고, 베이킹으로 디테일을 옮긴다. 자세한 절차는
         docs/blender_pipeline.md 4~5장.

버전 주의
  블렌더 API는 4.1에서 Auto Smooth가 제거되고, 4.2에서 EEVEE가 EEVEE Next로 바뀌었다.
  이 스크립트는 존재하는 프로퍼티만 건드리고, 없으면 경고만 남기고 계속 진행한다.
  (bpy가 없는 환경에서도 import할 수 있게 bpy는 선택적으로 불러온다 - 테스트용)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

try:  # 블렌더 밖(테스트/문서 도구)에서도 순수 함수를 쓸 수 있게
    import bpy  # type: ignore  # noqa: F401
    from mathutils import Vector  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover - 블렌더 밖
    bpy = None  # type: ignore
    Vector = None  # type: ignore


LOG_PREFIX = "[ai3d] "
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".bmp", ".webp"}

# GUI에서 실행할 때 쓰는 기본값 (Scripting 탭 Run Script)
SETTINGS: dict[str, object] = {
    "model": "",                       # 예: r"C:/project/ai3d/output/hero/model.glb"
    "textures": "",                    # 비우면 <모델 폴더>/textures
    "blend": "",                       # 예: r"C:/project/ai3d/output/hero/hero.blend"
    "name": "",
    "scale_target": 0.0,               # 최대 치수를 이 미터 값으로 정규화 (0=끔)
    "origin": "none",                  # none | bottom | center
    "smooth_angle": 30.0,              # -1이면 플랫 셰이딩
    "merge_distance": 0.0001,          # 0이면 병합 안 함
    "recalc_normals": False,
    "target_tris": 0,                  # 경로 B: 목표 삼각형 수 (예: 5000/10000/30000)
    "decimate": 0.0,                   # 경로 B: 비율 직접 지정 (0<r<1)
    "decimate_mode": "collapse",       # collapse | unsubdiv | dissolve
    "decimate_symmetry": False,        # 캐릭터 좌우 대칭 유지
    "symmetry_axis": "X",
    "quadriflow_faces": 0,
    "voxel_size": 0.0,
    "unwrap": "auto",                  # auto | smart | keep
    "bake": "",                        # "normal,ao,roughness,basecolor,metallic"
    "bake_size": 2048,
    "bake_dir": "",
    "bake_samples": 32,
    "bake_margin": 8,
    "cage_extrusion": 0.0,             # 0이면 모델 크기의 1%
    "bake_gpu": False,
    "ao_mode": "multiply",
    "normal_strength": 1.0,
    "roughness_scale": 1.0,
    "metallic_scale": 1.0,
    "alpha": "opaque",
    "export_fbx": "",
    "export_glb": "",
    "clear_scene": False,
    "drop_high": False,
}


# --------------------------------------------------------------------------- #
# 순수 함수: 텍스처 이름 해석
# --------------------------------------------------------------------------- #
_TOKEN_SPLIT = None
_GROUP_TOKEN = None


def _regexes():
    global _TOKEN_SPLIT, _GROUP_TOKEN
    import re

    if _TOKEN_SPLIT is None:
        _TOKEN_SPLIT = re.compile(r"[^0-9a-zA-Z]+")
        _GROUP_TOKEN = re.compile(r"^m(\d+)$")
    return _TOKEN_SPLIT, _GROUP_TOKEN


def tokenize(filename: str | Path) -> list[str]:
    """파일 이름을 소문자 토큰 목록으로 나눈다.

    T_Chair_BaseColor.png  -> ['t', 'chair', 'base', 'color']
    T_Chair_ORM.png        -> ['t', 'chair', 'orm']
    """
    import re

    split, _ = _regexes()
    stem = Path(str(filename)).stem
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", stem)
    return [token.lower() for token in split.split(spaced) if token]


def classify_tokens(tokens: list[str]) -> str | None:
    """토큰 목록 -> 텍스처 슬롯 이름. 우선순위가 높은 것부터 검사한다.

    'orm'을 부분 문자열로 찾으면 'normal'에도 걸리므로(n-o-r-m) 반드시 토큰 단위로 본다.
    """
    token_set = set(tokens)

    def has(*names: str) -> bool:
        return any(name in token_set for name in names)

    if has("normal", "normalmap", "nrm", "norm"):
        return "normal"
    if has("orm", "arm", "occlusionroughnessmetallic", "rma"):
        return "orm"
    if (has("metallic") and has("roughness")) or has("metallicroughness", "mr"):
        return "metallic_roughness"
    if has("roughness", "rough", "rgh", "glossiness", "smoothness"):
        return "roughness"
    if has("metallic", "metalness", "metal"):
        return "metallic"
    if has("occlusion", "ao", "ambientocclusion"):
        return "occlusion"
    if has("basecolor", "albedo", "diffuse", "bc") or (has("base") and has("color")) or has("color", "col"):
        return "basecolor"
    if has("emissive", "emission", "emit"):
        return "emissive"
    if has("height", "displacement", "disp"):
        return "height"
    return None


def parse_texture_name(filename: str | Path) -> tuple[str, str | None]:
    """파일 이름 -> (머티리얼 그룹, 슬롯).

    그룹은 glb_texture_tools가 멀티 머티리얼에 붙이는 'm0_', 'm1_' 접두사에서 얻는다.
    슬롯을 알아보지 못하면 (그룹, None).
    """
    tokens = tokenize(filename)
    _, group_pattern = _regexes()
    group = ""
    for token in tokens:
        match = group_pattern.match(token)
        if match:
            group = f"m{match.group(1)}"
            break
    return group, classify_tokens(tokens)


def _pick_better(candidate: Path, current: Path, stem: str) -> bool:
    """같은 슬롯에 후보가 여럿일 때 더 그럴듯한 파일을 고른다."""
    def score(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        stem_hit = 0 if (stem and stem.lower() in name) else 1
        return (stem_hit, len(name), name)
    return score(candidate) < score(current)


def discover_textures(
    directory: str | Path,
    stem: str = "",
    warnings: list[str] | None = None,
) -> dict[str, dict[str, Path]]:
    """폴더에서 PBR 슬롯별 텍스처를 찾아 {그룹: {슬롯: 경로}}로 돌려준다.

    같은 슬롯에 파일이 여러 개면 모델 이름과 겹치는 것, 이름이 짧은 것을 고르고
    경고를 남긴다(추측으로 조용히 넘어가지 않는다).
    """
    warnings = warnings if warnings is not None else []
    folder = Path(directory)
    groups: dict[str, dict[str, Path]] = {}

    if not folder.is_dir():
        warnings.append(f"텍스처 폴더가 없습니다: {folder}")
        return groups

    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        group, slot = parse_texture_name(path.name)
        if not slot:
            continue
        bucket = groups.setdefault(group, {})
        current = bucket.get(slot)
        if current is None:
            bucket[slot] = path
        elif _pick_better(path, current, stem):
            warnings.append(f"'{slot}' 후보가 둘 이상: {current.name} 대신 {path.name} 사용")
            bucket[slot] = path
        else:
            warnings.append(f"'{slot}' 후보가 둘 이상: {path.name} 무시")
    return groups


def plan_channels(maps: dict[str, Path], ao_mode: str = "multiply") -> dict[str, object]:
    """슬롯별 파일 -> 채널 라우팅 계획.

    각 값은 다음 중 하나다.
        ("file", Path, None)                    파일 전체를 그대로 사용
        ("orm", Path, "G")                      ORM의 한 채널
        ("metallic_roughness", Path, "B")       glTF MR의 한 채널
        ("occlusion", Path, "R")                개별 AO 텍스처
        None                                    없음

    우선순위
        ORM(R/G/B) > metallic_roughness(G/B) + occlusion(R) > 개별 roughness/metallic
        개별 채널 텍스처가 있으면 패킹 결과의 해당 채널만 덮어쓴다.
    """
    plan: dict[str, object] = {
        "basecolor": None, "normal": None, "roughness": None,
        "metallic": None, "ao": None, "emissive": None, "height": None,
        "notes": [],
    }
    notes: list[str] = plan["notes"]  # type: ignore[assignment]

    orm = maps.get("orm")
    mr = maps.get("metallic_roughness")

    if orm:
        plan["roughness"] = ("orm", orm, "G")
        plan["metallic"] = ("orm", orm, "B")
        plan["ao"] = ("orm", orm, "R")
        if mr:
            notes.append("ORM과 metallic_roughness가 모두 있습니다. ORM을 쓰고 MR은 무시합니다.")
    elif mr:
        plan["roughness"] = ("metallic_roughness", mr, "G")
        plan["metallic"] = ("metallic_roughness", mr, "B")
        notes.append("metallic_roughness만 있습니다. R 채널의 AO는 없으므로 AO 없이 구성합니다.")

    if maps.get("occlusion"):
        plan["ao"] = ("occlusion", maps["occlusion"], "R")

    if maps.get("roughness"):
        plan["roughness"] = ("file", maps["roughness"], None)
        if orm or mr:
            notes.append("개별 roughness 텍스처가 패킹된 G 채널을 덮어씁니다.")
    if maps.get("metallic"):
        plan["metallic"] = ("file", maps["metallic"], None)
        if orm or mr:
            notes.append("개별 metallic 텍스처가 패킹된 B 채널을 덮어씁니다.")

    for slot in ("basecolor", "normal", "emissive", "height"):
        if maps.get(slot):
            plan[slot] = ("file", maps[slot], None)

    if not plan["basecolor"]:
        notes.append("basecolor 텍스처가 없습니다. 단색/임베디드 머티리얼 값을 유지합니다.")
    if not plan["normal"]:
        notes.append("normal 텍스처가 없습니다. 노멀 입력을 비워 둡니다.")

    if ao_mode == "ignore" and plan["ao"]:
        plan["ao"] = None
        notes.append("--ao-mode ignore: AO 텍스처를 연결하지 않습니다.")
    return plan


def ratio_for_target(current_triangles: int, target_triangles: int) -> float:
    """Decimate Collapse의 ratio(0~1)를 목표 삼각형 수에서 역산한다."""
    if current_triangles <= 0 or target_triangles <= 0:
        return 0.0
    return min(1.0, max(0.0, target_triangles / current_triangles))


def scale_factor_for(max_dimension: float, target_size: float) -> float:
    """최대 치수를 target_size로 맞추는 배율. 0 이하 입력이면 1.0(변경 없음)."""
    if max_dimension <= 0 or target_size <= 0:
        return 1.0
    return target_size / max_dimension


BAKE_KINDS = ("normal", "ao", "roughness", "basecolor", "metallic")


def parse_bake_types(value: str) -> list[str]:
    """'normal,ao,roughness' -> ['normal', 'ao', 'roughness']."""
    result: list[str] = []
    for raw in str(value).split(","):
        name = raw.strip().lower()
        if not name:
            continue
        if name not in BAKE_KINDS:
            raise ValueError(f"지원하지 않는 베이킹 종류: {name} (가능: {', '.join(BAKE_KINDS)})")
        if name not in result:
            result.append(name)
    return result


def describe_route(target_tris: int = 0, decimate: float = 0.0, bake: list[str] | None = None) -> str:
    """의사결정 트리에서 어느 경로인지 한 줄로 알려 준다(리포트/로그용)."""
    if (target_tris and target_tris > 0) or (decimate and 0 < decimate < 1):
        return "B (캐릭터/모바일 - 리토폴로지 + 폴리곤 감면" + (" + 베이킹)" if bake else ")")
    return "A (원본 고밀도 유지 - UE5 Nanite 정적 프랍)"


# --------------------------------------------------------------------------- #
# 블렌더 헬퍼
# --------------------------------------------------------------------------- #
def log(message: str) -> None:
    print(LOG_PREFIX + message, flush=True)


def warn(message: str, warnings: list[str] | None = None) -> None:
    print(LOG_PREFIX + "WARN " + message, flush=True)
    if warnings is not None:
        warnings.append(message)


def _require_bpy() -> None:
    if bpy is None:
        raise RuntimeError(
            "이 스크립트는 블렌더에서 실행해야 합니다. "
            "blender --background --python pipeline/blender_import.py -- --model <파일>"
        )


def _selection(objects: list, active=None) -> None:
    _require_bpy()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        try:
            obj.select_set(True)
        except Exception:  # noqa: BLE001 - 다른 씬/컬렉션의 오브젝트
            pass
    if active is not None:
        bpy.context.view_layer.objects.active = active
    elif objects:
        bpy.context.view_layer.objects.active = objects[0]


def _override(obj):
    """bpy.context.temp_override용 컨텍스트 (3.2+)."""
    return bpy.context.temp_override(
        object=obj,
        active_object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    )


def triangle_count(obj) -> int:
    mesh = obj.data
    try:
        mesh.calc_loop_triangles()
    except Exception:  # noqa: BLE001
        pass
    return len(getattr(mesh, "loop_triangles", []))


def world_dimensions(objects: list):
    """오브젝트들의 월드 바운딩 박스 크기 (x, y, z)."""
    inf = float("inf")
    lower = [inf, inf, inf]
    upper = [-inf, -inf, -inf]
    found = False
    for obj in objects:
        if getattr(obj, "type", "") != "MESH" or obj.data is None:
            continue
        corners = getattr(obj, "bound_box", None)
        if not corners:
            continue
        matrix = obj.matrix_world
        for corner in corners:
            point = matrix @ Vector(corner)
            found = True
            for axis in range(3):
                lower[axis] = min(lower[axis], point[axis])
                upper[axis] = max(upper[axis], point[axis])
    if not found:
        return (0.0, 0.0, 0.0)
    return tuple(upper[i] - lower[i] for i in range(3))


# --------------------------------------------------------------------------- #
# 1) 임포트
# --------------------------------------------------------------------------- #
def import_model(path: Path, warnings: list[str]) -> list:
    _require_bpy()
    if not path.exists():
        raise FileNotFoundError(f"모델 파일이 없습니다: {path}")

    before = set(bpy.data.objects)
    suffix = path.suffix.lower()

    if suffix in {".glb", ".gltf"}:
        log(f"glTF 임포트: {path}")
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        log(f"FBX 임포트: {path}")
        try:
            bpy.ops.import_scene.fbx(
                filepath=str(path),
                use_custom_normals=True,
                global_scale=1.0,
                apply_unit_scale=True,
                apply_scale_options="FBX_SCALE_NONE",
                axis_forward="-Z",
                axis_up="Y",
            )
        except TypeError as exc:  # 버전별 인자 차이
            warn(f"FBX 임포트 인자 일부가 이 버전에 없습니다({exc}). 기본값으로 다시 시도합니다.", warnings)
            bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise ValueError(f"지원하지 않는 포맷: {suffix} (glb/gltf/fbx)")

    new_objects = [obj for obj in bpy.data.objects if obj not in before]
    meshes = [obj for obj in new_objects if getattr(obj, "type", "") == "MESH"]
    if not meshes:
        raise RuntimeError(f"임포트된 메시가 없습니다: {path}")

    for obj in meshes:
        if obj.data.users > 1:
            obj.data = obj.data.copy()
    log(f"메시 {len(meshes)}개 임포트: {', '.join(obj.name for obj in meshes)}")
    return meshes


# --------------------------------------------------------------------------- #
# 2) 메시 검사 / 정리
# --------------------------------------------------------------------------- #
def inspect_mesh(obj) -> dict:
    """고밀도 원본을 받은 직후의 상태를 기록한다(경로 판단 근거)."""
    import bmesh

    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        non_manifold = sum(1 for edge in bm.edges if not edge.is_manifold)
        degenerate = sum(1 for face in bm.faces if face.calc_area() < 1e-12)
        ngons = sum(1 for face in bm.faces if len(face.verts) > 4)
    finally:
        bm.free()

    info = {
        "name": obj.name,
        "triangles": triangle_count(obj),
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "non_manifold_edges": non_manifold,
        "degenerate_faces": degenerate,
        "ngons": ngons,
        "uv_layers": [layer.name for layer in mesh.uv_layers],
        "materials": [slot.material.name for slot in obj.material_slots if slot.material],
        "custom_normals": bool(getattr(mesh, "has_custom_normals", False)),
        "shape_keys": bool(getattr(mesh, "shape_keys", None)),
        "dimensions": [round(value, 4) for value in obj.dimensions],
    }
    log(
        "  검사 {name}: {tris:,} 삼각형 / {verts:,} 버텍스 / 비매니폴드 {nm:,} 엣지 / UV {uv} / 머티리얼 {mat}".format(
            name=info["name"], tris=info["triangles"], verts=info["vertices"],
            nm=non_manifold, uv=len(info["uv_layers"]), mat=len(info["materials"]),
        )
    )
    return info


def merge_by_distance(obj, distance: float) -> int:
    """중복 버텍스 병합. AI 생성 메시는 정점이 붙지 않은 삼각형 더미인 경우가 많다."""
    import bmesh

    mesh = obj.data
    before = len(mesh.vertices)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=distance)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    removed = before - len(mesh.vertices)
    if removed:
        log(f"  {obj.name}: 중복 버텍스 {removed}개 병합 (dist={distance})")
    return removed


def recalc_normals(obj) -> None:
    import bmesh

    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def shade_smooth_by_angle(obj, angle_degrees: float) -> None:
    """각도 기준 스무스 셰이딩.

    4.1+ 에서 Mesh.use_auto_smooth가 제거됐다. 백그라운드에서
    bpy.ops.object.shade_auto_smooth가 CANCELLED로 끝나 아무것도 붙지 않는 사례가 있어,
    파괴적이지만 확실한 Mesh.set_sharp_from_angle을 우선 사용한다.
    """
    mesh = obj.data
    version = tuple(bpy.app.version)
    if version >= (4, 1, 0):
        try:
            mesh.set_sharp_from_angle(angle=math.radians(angle_degrees))
            for polygon in mesh.polygons:
                polygon.use_smooth = True
            return
        except AttributeError:
            pass
    try:
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(angle_degrees)
    except AttributeError:
        pass
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def shade_flat(obj) -> None:
    for polygon in obj.data.polygons:
        polygon.use_smooth = False


def set_origin(obj, mode: str) -> None:
    """메시 데이터를 옮겨 원점을 바닥 중앙/중심으로 맞춘다(월드 위치는 유지)."""
    if mode == "none" or not obj.data.vertices:
        return
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    if mode == "bottom":
        offset = [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, min(zs)]
    elif mode == "center":
        offset = [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, (min(zs) + max(zs)) / 2.0]
    else:
        return
    if all(abs(value) < 1e-9 for value in offset):
        return
    for vert in obj.data.vertices:
        vert.co.x -= offset[0]
        vert.co.y -= offset[1]
        vert.co.z -= offset[2]
    obj.data.update()
    obj.location = obj.location + (obj.matrix_world.to_3x3() @ Vector(offset))


def normalize_scale(meshes: list, target_size: float, warnings: list[str]) -> float:
    dims = world_dimensions(meshes)
    factor = scale_factor_for(max(dims), target_size)
    if factor == 1.0:
        return factor

    roots = [obj for obj in meshes if obj.parent is None] or meshes
    for obj in roots:
        obj.scale = obj.scale * factor
    bpy.context.view_layer.update()

    try:
        _selection(roots)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    except Exception as exc:  # noqa: BLE001
        warn(f"변환 적용 실패({exc}). 오브젝트 스케일로 남겨 둡니다.", warnings)

    for obj in meshes:
        if obj.parent is not None:
            warn(f"{obj.name}는 부모가 있어 스케일이 상속됩니다. 부모 Empty를 확인하세요.", warnings)
            break
    log(f"스케일 정규화: 최대 {max(dims):.3f}m -> {target_size}m (x{factor:.4f})")
    return factor


# --------------------------------------------------------------------------- #
# 3) 로우폴리 생성 / 폴리곤 감면 (경로 B)
# --------------------------------------------------------------------------- #
def prepare_low_poly(high, base_name: str):
    """하이폴리를 보존하고, 같은 위치에 로우폴리 사본을 만든다.

    반환: (high, low). high는 '<base>_High', low는 '<base>_Low'로 이름을 바꾼다.
    """
    base = base_name or high.name
    high.name = f"{base}_High"
    high.data.name = high.name
    low = high.copy()
    low.data = high.data.copy()
    low.name = f"{base}_Low"
    low.data.name = low.name
    collections = list(getattr(high, "users_collection", []) or [bpy.context.scene.collection])
    for collection in collections:
        collection.objects.link(low)
    # 머티리얼을 공유하면 로우폴리 베이킹/최종 머티리얼 구성이 하이폴리 원본을 망친다.
    for index, material in enumerate(list(low.data.materials)):
        if material is not None:
            low.data.materials[index] = material.copy()
    log(f"로우폴리 사본 생성: {high.name} -> {low.name}")
    return high, low


def apply_modifier(obj, modifier) -> None:
    _selection([obj])
    with _override(obj):
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def decimate(obj, ratio: float, mode: str = "collapse", symmetry: bool = False,
             symmetry_axis: str = "X") -> dict:
    """Decimate 모디파이어로 삼각형을 줄인다. 반환값은 before/after 통계."""
    before = triangle_count(obj)
    modifier = obj.modifiers.new(name="AI3D_Decimate", type="DECIMATE")
    if mode == "collapse":
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = max(0.0001, min(1.0, ratio))
        modifier.use_collapse_triangulate = True
        if symmetry:
            try:
                modifier.use_symmetry = True
                modifier.symmetry_axis = symmetry_axis
            except Exception:  # noqa: BLE001 - 버전 차이
                warn("Decimate 대칭 옵션을 켜지 못했습니다.")
    elif mode == "unsubdiv":
        modifier.decimate_type = "UNSUBDIV"
        modifier.iterations = max(1, int(round((1.0 - ratio) * 10)))
    elif mode == "dissolve":
        modifier.decimate_type = "DISSOLVE"
        modifier.angle_limit = math.radians(5.0)
        modifier.use_dissolve_boundaries = False
    else:
        obj.modifiers.remove(modifier)
        raise ValueError(f"알 수 없는 decimate 모드: {mode}")

    try:
        apply_modifier(obj, modifier)
    except Exception as exc:  # noqa: BLE001
        obj.modifiers.remove(modifier)
        raise RuntimeError(f"Decimate 적용 실패({obj.name}): {exc}") from exc

    after = triangle_count(obj)
    log(f"  {obj.name}: Decimate({mode}) {before:,} -> {after:,} 삼각형")
    return {"object": obj.name, "before": before, "after": after}


def quadriflow(obj, target_faces: int) -> dict:
    before = triangle_count(obj)
    _selection([obj])
    try:
        with _override(obj):
            bpy.ops.object.quadriflow_remesh(target_faces=max(100, target_faces), use_mesh_symmetry=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Quadriflow 리메시 실패({obj.name}): {exc}") from exc
    after = triangle_count(obj)
    log(f"  {obj.name}: Quadriflow {before:,} -> {after:,} 삼각형")
    return {"object": obj.name, "before": before, "after": after}


def voxel_remesh(obj, voxel_size: float) -> dict:
    before = triangle_count(obj)
    modifier = obj.modifiers.new(name="AI3D_Remesh", type="REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = voxel_size
    modifier.use_smooth_shade = False
    try:
        apply_modifier(obj, modifier)
    except Exception as exc:  # noqa: BLE001
        obj.modifiers.remove(modifier)
        raise RuntimeError(f"Voxel Remesh 실패({obj.name}): {exc}") from exc
    after = triangle_count(obj)
    log(f"  {obj.name}: Voxel Remesh {before:,} -> {after:,} 삼각형")
    return {"object": obj.name, "before": before, "after": after}


# --------------------------------------------------------------------------- #
# 4) 머티리얼 노드 구성
# --------------------------------------------------------------------------- #
SOCKET_BASE = ("Base Color",)
SOCKET_METALLIC = ("Metallic",)
SOCKET_ROUGHNESS = ("Roughness",)
SOCKET_NORMAL = ("Normal",)
SOCKET_EMISSION = ("Emission Color", "Emission")
SOCKET_EMISSION_STRENGTH = ("Emission Strength",)
SOCKET_ALPHA = ("Alpha",)

CHANNEL_OUTPUT_NAMES = {"R": ("Red", "R"), "G": ("Green", "G"), "B": ("Blue", "B")}


def _socket(node, names, outputs: bool = False):
    sockets = node.outputs if outputs else node.inputs
    for name in names:
        try:
            if name in sockets:
                return sockets[name]
        except Exception:  # noqa: BLE001
            continue
    return None


def _load_image(path: Path, colorspace: str | None):
    image = bpy.data.images.load(str(path), check_existing=True)
    if colorspace:
        try:
            image.colorspace_settings.name = colorspace
        except Exception:  # noqa: BLE001 - 컬러 관리 설정이 없는 이미지
            pass
    return image


def _texture_node(nodes, path: Path, colorspace: str | None, location: tuple[float, float]):
    node = nodes.new("ShaderNodeTexImage")
    node.image = _load_image(path, colorspace)
    node.label = Path(path).name
    node.location = location
    node.interpolation = "Linear"
    return node


def _separate_channel(nodes, links, texture_node, channel: str, label: str, location):
    """Separate Color(3.3+) / Separate RGB(구버전)로 한 채널을 뽑는다."""
    try:
        separate = nodes.new("ShaderNodeSeparateColor")
        separate.mode = "RGB"
    except Exception:  # noqa: BLE001 - 3.3 미만
        separate = nodes.new("ShaderNodeSeparateRGB")
    separate.label = f"{label} {channel}"
    separate.location = location
    source_socket = _socket(separate, ("Color", "Image"))
    if source_socket is None:
        raise RuntimeError("Separate Color 입력 소켓을 찾지 못했습니다")
    links.new(texture_node.outputs["Color"], source_socket)
    output = _socket(separate, CHANNEL_OUTPUT_NAMES[channel], outputs=True)
    if output is None:
        raise RuntimeError(f"Separate Color에서 {channel} 출력을 찾지 못했습니다")
    return output


def _multiply(nodes, links, a, b, factor: float, location):
    """색 두 개를 곱한다. 4.x의 ShaderNodeMix를 우선 쓰고 구버전은 MixRGB."""
    try:
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = location
        # ShaderNodeMix의 RGBA 소켓은 이름이 중복돼 인덱스로 접근한다.
        # 입력: 0 Factor(float), 6 A(color), 7 B(color) / 출력: 2 Result(color)
        mix.inputs[0].default_value = factor
        links.new(a, mix.inputs[6])
        links.new(b, mix.inputs[7])
        return mix.outputs[2]
    except Exception:  # noqa: BLE001 - 3.4 미만
        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.location = location
        mix.inputs[0].default_value = factor
        links.new(a, mix.inputs[1])
        links.new(b, mix.inputs[2])
        return mix.outputs[0]


def _scale_value(nodes, links, value, scale: float, label: str, location):
    if abs(scale - 1.0) < 1e-6:
        return value
    node = nodes.new("ShaderNodeMath")
    node.operation = "MULTIPLY"
    node.label = label
    node.location = location
    node.inputs[1].default_value = scale
    links.new(value, node.inputs[0])
    return node.outputs[0]


def _set_alpha_mode(material, mode: str) -> None:
    """4.2+ EEVEE Next(surface_render_method)와 구버전(blend_method) 모두 시도."""
    if mode == "opaque":
        return
    try:
        material.surface_render_method = "BLENDED" if mode == "blend" else "DITHERED"
    except Exception:  # noqa: BLE001
        pass
    try:
        material.blend_method = "BLEND" if mode == "blend" else "CLIP"
    except Exception:  # noqa: BLE001
        pass
    if mode == "clip":
        try:
            material.alpha_threshold = 0.5
        except Exception:  # noqa: BLE001
            pass


def build_material(material, plan: dict, options: dict, warnings: list[str]) -> dict:
    """머티리얼 하나의 노드 트리를 새로 구성한다."""
    _require_bpy()
    try:
        material.use_nodes = True
    except Exception:  # noqa: BLE001 - 5.0+ 는 항상 노드 사용
        pass

    tree = material.node_tree
    if tree is None:
        raise RuntimeError(f"{material.name}: node_tree가 없습니다")
    nodes, links = tree.nodes, tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (60, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    info: dict[str, object] = {"material": material.name, "notes": list(plan.get("notes", []))}

    # --- Base Color (+ AO 곱연산) ---
    base_source = None
    base_node = None
    entry = plan.get("basecolor")
    if entry:
        base_node = _texture_node(nodes, entry[1], "sRGB", (-820, 340))
        base_source = base_node.outputs["Color"]
        info["basecolor"] = Path(entry[1]).name

    ao_entry = plan.get("ao")
    if ao_entry:
        ao_node = _texture_node(nodes, ao_entry[1], "Non-Color", (-1120, 0))
        ao_channel = _separate_channel(nodes, links, ao_node, ao_entry[2] or "R", "AO", (-900, 0))
        info["ao"] = Path(ao_entry[1]).name
        if options.get("ao_mode", "multiply") == "multiply" and base_source is not None:
            # Principled BSDF에는 AO 입력이 없다(3.x/4.x/5.x 공통).
            # glTF 뷰어와 같은 인상을 주려면 Base Color에 곱하는 것이 표준 대응이다.
            base_source = _multiply(
                nodes, links, base_source, ao_channel,
                float(options.get("ao_strength", 1.0)), (-520, 340),
            )
            info["ao_connection"] = "basecolor multiply"
        else:
            info["ao_connection"] = "kept (baking/engine 용)"
    base_socket = _socket(bsdf, SOCKET_BASE)
    if base_socket is not None:
        if base_source is not None:
            links.new(base_source, base_socket)
        else:
            base_socket.default_value = (0.8, 0.8, 0.8, 1.0)

    # --- Roughness / Metallic ---
    for key, socket_names, scale_key in (
        ("roughness", SOCKET_ROUGHNESS, "roughness_scale"),
        ("metallic", SOCKET_METALLIC, "metallic_scale"),
    ):
        channel_entry = plan.get(key)
        if not channel_entry:
            continue
        _, path, channel = channel_entry
        y = -260 if key == "roughness" else -560
        texture = _texture_node(nodes, path, "Non-Color", (-1120, y))
        if channel:
            value = _separate_channel(nodes, links, texture, channel, key.capitalize(), (-900, y))
        else:
            value = texture.outputs["Color"]
        value = _scale_value(
            nodes, links, value, float(options.get(scale_key, 1.0)),
            f"{key} x{options.get(scale_key, 1.0)}", (-660, y),
        )
        socket = _socket(bsdf, socket_names)
        if socket is not None:
            links.new(value, socket)
        info[key] = f"{Path(path).name}:{channel or 'RGB'}"

    # --- Normal ---
    normal_entry = plan.get("normal")
    if normal_entry:
        normal_texture = _texture_node(nodes, normal_entry[1], "Non-Color", (-820, -640))
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.label = "Normal Map (Tangent)"
        normal_map.location = (-320, -640)
        normal_map.space = "TANGENT"
        links.new(normal_texture.outputs["Color"], normal_map.inputs["Color"])
        if "Strength" in normal_map.inputs:
            normal_map.inputs["Strength"].default_value = float(options.get("normal_strength", 1.0))
        socket = _socket(bsdf, SOCKET_NORMAL)
        if socket is not None:
            links.new(normal_map.outputs["Normal"], socket)
        info["normal"] = Path(normal_entry[1]).name

    # --- Emissive ---
    emissive_entry = plan.get("emissive")
    if emissive_entry:
        emissive = _texture_node(nodes, emissive_entry[1], "sRGB", (-820, -900))
        color_socket = _socket(bsdf, SOCKET_EMISSION)
        if color_socket is not None:
            links.new(emissive.outputs["Color"], color_socket)
        strength_socket = _socket(bsdf, SOCKET_EMISSION_STRENGTH)
        if strength_socket is not None:
            strength_socket.default_value = 1.0
        info["emissive"] = Path(emissive_entry[1]).name

    # --- Alpha ---
    alpha_mode = str(options.get("alpha", "opaque"))
    if alpha_mode != "opaque" and base_node is not None and base_node.image is not None:
        channels = int(getattr(base_node.image, "channels", 4) or 4)
        if channels >= 4:
            alpha_socket = _socket(bsdf, SOCKET_ALPHA)
            if alpha_socket is not None:
                links.new(base_node.outputs["Alpha"], alpha_socket)
            _set_alpha_mode(material, alpha_mode)
            info["alpha"] = alpha_mode
        else:
            warn(f"{material.name}: basecolor에 알파 채널이 없어 alpha={alpha_mode}를 건너뜁니다.", warnings)

    if not plan.get("roughness") and not plan.get("metallic"):
        info["notes"].append("roughness/metallic 텍스처가 없습니다. Principled 기본값을 씁니다.")
    return info


def assign_materials(meshes: list, groups: dict[str, dict[str, Path]], options: dict,
                     warnings: list[str]) -> list[dict]:
    """오브젝트별 머티리얼 슬롯에 텍스처 그룹을 배정하고 노드를 구성한다."""
    reports: list[dict] = []
    if not groups:
        warn("텍스처를 찾지 못해 머티리얼 재구성을 건너뜁니다(임포트된 머티리얼 유지).", warnings)
        return reports

    default_group = groups.get("") or {}
    for obj in meshes:
        slots = list(obj.material_slots)
        if not slots:
            material = bpy.data.materials.new(name=f"AI3D_{obj.name}")
            obj.data.materials.append(material)
            slots = list(obj.material_slots)

        for index, slot in enumerate(slots):
            material = slot.material
            if material is None:
                material = bpy.data.materials.new(name=f"AI3D_{obj.name}_{index}")
                slot.material = material
            group_maps = groups.get(f"m{index}") or default_group
            if not group_maps:
                warn(f"{obj.name} 슬롯 {index}: 텍스처 그룹이 비어 있습니다.", warnings)
                continue
            plan = plan_channels(group_maps, ao_mode=str(options.get("ao_mode", "multiply")))
            try:
                info = build_material(material, plan, options, warnings)
            except Exception as exc:  # noqa: BLE001 - 한 머티리얼 실패로 전체를 멈추지 않는다
                warn(f"{material.name} 노드 구성 실패: {exc}", warnings)
                traceback.print_exc()
                continue
            info["object"] = obj.name
            reports.append(info)
    return reports


# --------------------------------------------------------------------------- #
# 5) UV / 케이지
# --------------------------------------------------------------------------- #
def ensure_uv(obj, method: str, warnings: list[str]) -> bool:
    """로우폴리 UV를 준비한다.

    method
      keep  : 기존 UV 유지(하이폴리에서 물려받은 UV도 그대로)
      smart : 기존 UV를 지우고 Smart UV Project (자동 폴백, 캐릭터에는 부적합)
      auto  : UV가 없을 때만 smart
    """
    mesh = obj.data
    if method == "keep" and mesh.uv_layers:
        return True
    if method == "auto" and mesh.uv_layers:
        warn(
            f"{obj.name}: 하이폴리에서 물려받은 UV를 그대로 씁니다. "
            "베이킹 결과의 텍셀 밀도가 고르지 않을 수 있습니다(캐릭터는 수동 언랩 권장).",
            warnings,
        )
        return True

    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    log(f"  {obj.name}: Smart UV Project로 UV 생성")
    try:
        _selection([obj])
        with _override(obj):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:  # noqa: BLE001
            pass
        warn(f"{obj.name}: UV 생성 실패({exc}). Edit Mode에서 직접 언랩하세요.", warnings)
        return False


def build_cage(low, extrusion: float, warnings: list[str]):
    """로우폴리를 노멀 방향으로 부풀린 베이킹 케이지 오브젝트를 만든다.

    케이지가 있으면 하이폴리와 로우폴리 사이를 감싸는 광선을 쏘므로
    실루엣이 다른 부분에서도 노멀이 새지 않는다.
    """
    try:
        import bmesh

        cage = low.copy()
        cage.data = low.data.copy()
        cage.name = f"{low.name}_Cage"
        cage.data.name = cage.name
        for collection in list(getattr(low, "users_collection", []) or [bpy.context.scene.collection]):
            collection.objects.link(cage)

        bm = bmesh.new()
        try:
            bm.from_mesh(cage.data)
            bm.normal_update()
            for vert in bm.verts:
                vert.co += vert.normal * extrusion
            bm.to_mesh(cage.data)
        finally:
            bm.free()
        cage.data.update()
        cage.hide_render = True
        cage.hide_set(False)  # 베이크가 케이지 지오메트리를 읽는다. 끝난 뒤 숨긴다.
        log(f"  케이지 생성: {cage.name} (extrusion={extrusion:.4f})")
        return cage
    except Exception as exc:  # noqa: BLE001
        warn(f"케이지 생성 실패({exc}). cage extrusion 없이 베이킹합니다.", warnings)
        return None


# --------------------------------------------------------------------------- #
# 6) 베이킹 (하이폴리 -> 로우폴리)
# --------------------------------------------------------------------------- #
def _bake_environment(scene, samples: int, gpu: bool, warnings: list[str]) -> None:
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.samples = max(1, samples)
        scene.cycles.use_denoising = False
        if gpu:
            scene.cycles.device = "GPU"
            preferences = bpy.context.preferences.addons.get("cycles")
            if preferences is not None:
                preferences.preferences.compute_device_type = "OPTIX"
                preferences.preferences.get_devices()
                for device in preferences.preferences.devices:
                    device.use = device.type != "CPU"
    except Exception as exc:  # noqa: BLE001
        warn(f"Cycles 설정 일부를 바꾸지 못했습니다: {exc}", warnings)


def _swap_materials_to_emission(high):
    """EMIT 베이킹용으로 하이폴리 머티리얼의 Metallic 입력을 Emission으로 바꾼다.

    basecolor/roughness는 DIFFUSE/ROUGHNESS 베이크가 하이폴리의 셰이더를 그대로
    평가하지만, metallic은 베이크 타입이 없어 EMIT 트릭을 쓴다.
    반환값은 복원용 목록.
    """
    saved = []
    for material in getattr(high.data, "materials", []) or []:
        if material is None or not getattr(material, "use_nodes", False) or material.node_tree is None:
            continue
        tree = material.node_tree
        nodes, links = tree.nodes, tree.links
        output = next((node for node in nodes if node.type == "OUTPUT_MATERIAL"), None)
        if output is None or "Surface" not in output.inputs:
            continue
        surface = output.inputs["Surface"]
        original = surface.links[0].from_socket if surface.is_linked else None
        bsdf = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        emission = nodes.new("ShaderNodeEmission")
        emission.label = "AI3D_MetallicBake"
        emission.location = (output.location[0] - 300, output.location[1])
        if bsdf is not None:
            metallic = _socket(bsdf, SOCKET_METALLIC)
            if metallic is not None:
                if metallic.is_linked:
                    links.new(metallic.links[0].from_socket, emission.inputs["Color"])
                else:
                    value = float(metallic.default_value)
                    emission.inputs["Color"].default_value = (value, value, value, 1.0)
            else:
                warn(f"{material.name}: Principled Metallic 소켓이 없어 메탈릭 베이크가 검게 나올 수 있습니다.")
        emission.inputs["Strength"].default_value = 1.0
        links.new(emission.outputs["Emission"], surface)
        saved.append((tree, surface, original, emission))
    return saved


def _restore_materials(saved) -> None:
    for tree, surface, original, emission in saved:
        try:
            if original is not None:
                tree.links.new(original, surface)
            else:
                for link in list(surface.links):
                    tree.links.remove(link)
            tree.nodes.remove(emission)
        except Exception:  # noqa: BLE001
            pass


def bake_high_to_low(low, high, out_dir: Path, size: int, bake_types: list[str],
                     margin: int, extrusion: float, samples: int, gpu: bool,
                     cage, warnings: list[str]) -> dict:
    """하이폴리 디테일을 로우폴리 UV로 베이킹한다.

    normal  : 탄젠트 공간 (+Y, OpenGL 규약). UE5는 DirectX라 임포트 시 Green 반전 필요.
    ao      : 앰비언트 오클루전.
    roughness / basecolor : 도포된 셰이더를 하이폴리에서 평가해 전이.
    metallic: EMIT 트릭(위 _swap_materials_to_emission).
    """
    _require_bpy()
    if not low.data.materials:
        low.data.materials.append(bpy.data.materials.new(name=f"AI3D_{low.name}_bake"))

    # 모든 머티리얼 슬롯에 같은 베이크 타깃 이미지를 물린다. 슬롯 하나라도
    # 활성 이미지 노드가 없으면 Blender가 베이크를 중단하기 때문이다.
    targets: list[tuple] = []
    for slot in low.material_slots:
        material = slot.material
        if material is None:
            continue
        try:
            material.use_nodes = True
        except Exception:  # noqa: BLE001
            pass
        if material.node_tree is None:
            warn(f"{low.name}/{material.name}: node_tree가 없어 베이킹에서 제외합니다.", warnings)
            continue
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.label = "AI3D_BakeTarget"
        node.location = (60, 700)
        targets.append((material, node))
    if not targets:
        warn(f"{low.name}: 베이킹 대상 머티리얼이 없습니다.", warnings)
        return {}
    if len(targets) > 1:
        log(f"  {low.name}: 머티리얼 {len(targets)}개의 UV를 하나의 텍스처에 함께 베이크합니다.")

    scene = bpy.context.scene
    bake = scene.render.bake
    bake.use_selected_to_active = True
    bake.use_cage = cage is not None
    if cage is not None:
        try:
            bake.cage_object = cage
        except Exception as exc:  # noqa: BLE001
            warn(f"케이지 오브젝트를 지정하지 못했습니다({exc}). extrusion으로 대체합니다.", warnings)
            bake.use_cage = False
    bake.cage_extrusion = extrusion
    bake.max_ray_distance = 0.0
    bake.margin = margin
    bake.use_clear = True
    try:
        bake.margin_type = "ADJACENT_FACES"
    except Exception:  # noqa: BLE001
        pass
    _bake_environment(scene, samples, gpu, warnings)

    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    high.hide_set(False)
    high.hide_render = False

    for kind in bake_types:
        image = bpy.data.images.new(
            name=f"T_{low.name}_{kind}", width=size, height=size,
            alpha=(kind == "basecolor"), float_buffer=False,
        )
        if kind != "basecolor":
            try:
                image.colorspace_settings.name = "Non-Color"
            except Exception:  # noqa: BLE001
                pass
        for material, node in targets:
            node.image = image
            nodes = material.node_tree.nodes
            nodes.active = node
            for other in nodes:
                try:
                    other.select = other is node
                except Exception:  # noqa: BLE001
                    pass

        saved = _swap_materials_to_emission(high) if kind == "metallic" else []
        try:
            _selection([high], active=low)
            high.select_set(True)
            low.select_set(True)
            log(f"  베이킹 {kind}: {high.name} -> {low.name} ({size}px, samples={samples})")
            if kind == "normal":
                bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT",
                                    use_selected_to_active=True, use_clear=True, margin=margin)
            elif kind == "ao":
                bpy.ops.object.bake(type="AO",
                                    use_selected_to_active=True, use_clear=True, margin=margin)
            elif kind == "roughness":
                bpy.ops.object.bake(type="ROUGHNESS",
                                    use_selected_to_active=True, use_clear=True, margin=margin)
            elif kind == "basecolor":
                bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"},
                                    use_selected_to_active=True, use_clear=True, margin=margin)
            elif kind == "metallic":
                bpy.ops.object.bake(type="EMIT",
                                    use_selected_to_active=True, use_clear=True, margin=margin)
        except Exception as exc:  # noqa: BLE001
            warn(f"{kind} 베이킹 실패: {exc}", warnings)
            bpy.data.images.remove(image)
            _restore_materials(saved)
            continue
        finally:
            _restore_materials(saved)

        target_path = out_dir / f"T_{low.name}_{kind}.png"
        image.filepath_raw = str(target_path)
        image.file_format = "PNG"
        try:
            image.save()
            results[kind] = str(target_path)
            log(f"  저장: {target_path}")
        except Exception as exc:  # noqa: BLE001
            warn(f"{kind} 이미지 저장 실패: {exc}", warnings)
        for material, node in targets:
            node.image = None
        bpy.data.images.remove(image)

    for material, node in targets:
        try:
            material.node_tree.nodes.remove(node)
        except Exception:  # noqa: BLE001
            pass
    if high is not low:
        high.hide_set(True)
    if cage is not None:
        try:
            cage.hide_set(True)
        except Exception:  # noqa: BLE001
            pass
    return results


# --------------------------------------------------------------------------- #
# 7) 익스포트
# --------------------------------------------------------------------------- #
def export_fbx(path: Path, objects: list, warnings: list[str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    _selection(objects)
    kwargs = dict(
        filepath=str(path), use_selection=True, object_types={"MESH"},
        apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
        axis_forward="-Z", axis_up="Y", mesh_smooth_type="FACE",
        use_mesh_modifiers=True, add_leaf_bones=False,
        path_mode="COPY", embed_textures=False, bake_anim=False,
    )
    try:
        bpy.ops.export_scene.fbx(**kwargs)
    except TypeError as exc:
        warn(f"FBX 익스포트 인자 일부가 이 버전에 없습니다({exc}). 최소 인자로 다시 시도합니다.", warnings)
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True)
    log(f"FBX 저장: {path}")
    return str(path)


def export_glb(path: Path, objects: list, warnings: list[str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    _selection(objects)
    kwargs = dict(
        filepath=str(path), export_format="GLB", use_selection=True,
        export_apply=True, export_yup=True, export_materials="EXPORT",
        export_image_format="AUTO", export_normals=True, export_texcoords=True,
    )
    try:
        bpy.ops.export_scene.gltf(**kwargs)
    except TypeError as exc:
        warn(f"glTF 익스포트 인자 일부가 이 버전에 없습니다({exc}). 최소 인자로 다시 시도합니다.", warnings)
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True)
    log(f"GLB 저장: {path}")
    return str(path)


# --------------------------------------------------------------------------- #
# 8) 실행
# --------------------------------------------------------------------------- #
def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    log("씬의 기존 오브젝트를 삭제했습니다.")


def _material_options(settings: dict) -> dict:
    return {
        "ao_mode": settings.get("ao_mode", "multiply"),
        "ao_strength": settings.get("ao_strength", 1.0),
        "normal_strength": settings.get("normal_strength", 1.0),
        "roughness_scale": settings.get("roughness_scale", 1.0),
        "metallic_scale": settings.get("metallic_scale", 1.0),
        "alpha": settings.get("alpha", "opaque"),
    }


def run(settings: dict) -> dict:
    _require_bpy()
    warnings: list[str] = []
    report: dict[str, object] = {
        "blender": ".".join(str(part) for part in bpy.app.version),
        "warnings": warnings,
    }

    model_value = str(settings.get("model") or "").strip()
    if not model_value:
        raise ValueError("model 경로가 필요합니다 (SETTINGS['model'] 또는 --model)")
    model = Path(model_value).expanduser()
    report["model"] = str(model)

    textures_value = str(settings.get("textures") or "").strip()
    texture_dir = Path(textures_value).expanduser() if textures_value else model.parent / "textures"
    report["textures_dir"] = str(texture_dir)

    target_tris = int(settings.get("target_tris") or 0)
    decimate_ratio = float(settings.get("decimate") or 0.0)
    bake_types = parse_bake_types(str(settings.get("bake") or ""))
    reduction_mode = target_tris > 0 or 0 < decimate_ratio < 1
    retopo_mode = reduction_mode or bool(bake_types)
    report["route"] = describe_route(target_tris, decimate_ratio, bake_types)
    log(f"경로: {report['route']}")

    if settings.get("clear_scene"):
        clear_scene()

    # 1) 임포트 + 검사
    meshes = import_model(model, warnings)
    report["inspection"] = [inspect_mesh(obj) for obj in meshes]

    # 2) 정리
    merge_distance = float(settings.get("merge_distance") or 0.0)
    for obj in meshes:
        if merge_distance > 0:
            merge_by_distance(obj, merge_distance)
        if settings.get("recalc_normals"):
            recalc_normals(obj)

    scale_target = float(settings.get("scale_target") or 0.0)
    if scale_target > 0:
        normalize_scale(meshes, scale_target, warnings)

    origin_mode = str(settings.get("origin") or "none")
    for obj in meshes:
        set_origin(obj, origin_mode)

    smooth_angle = float(settings.get("smooth_angle", 30.0))
    for obj in meshes:
        if smooth_angle < 0:
            shade_flat(obj)
        else:
            shade_smooth_by_angle(obj, smooth_angle)

    # 3) 하이폴리 머티리얼(원본 텍스처 기준) - 베이킹 소스가 올바르게 보이도록
    groups = discover_textures(texture_dir, stem=model.stem, warnings=warnings)
    report["textures"] = {
        group: {slot: path.name for slot, path in sorted(slots.items())}
        for group, slots in sorted(groups.items())
    }
    options = _material_options(settings)
    base_name = str(settings.get("name") or "").strip()
    if base_name:
        if len(meshes) == 1:
            meshes[0].name = base_name
            meshes[0].data.name = base_name
        else:
            for index, obj in enumerate(meshes):
                obj.name = f"{base_name}_{index:02d}"
                obj.data.name = obj.name

    materials_report: list[dict] = []
    if settings.get("materials", True):
        materials_report = assign_materials(meshes, groups, options, warnings)
    report["materials"] = materials_report

    # 4) 로우폴리 준비 + 감면 (경로 B)
    high_objects = list(meshes)
    low_objects: list = []
    reduction: list[dict] = []

    if reduction_mode:
        total_tris = sum(triangle_count(obj) for obj in meshes)
        if target_tris > 0:
            if decimate_ratio:
                warn("--target-tris와 --decimate를 함께 줬습니다. --target-tris를 사용합니다.", warnings)
            ratio = ratio_for_target(total_tris, target_tris)
            log(f"목표 삼각형 {target_tris:,} / 현재 {total_tris:,} -> ratio {ratio:.4f}")
        else:
            ratio = decimate_ratio

        low_to_high: dict[str, object] = {}
        for high in meshes:
            low_base = base_name if (base_name and len(meshes) == 1) else high.name
            source, low = prepare_low_poly(high, low_base)
            low_objects.append(low)
            low_to_high[low.name] = source

        for low in low_objects:
            try:
                if float(settings.get("voxel_size") or 0) > 0:
                    reduction.append(voxel_remesh(low, float(settings["voxel_size"])))
                if int(settings.get("quadriflow_faces") or 0) > 0:
                    reduction.append(quadriflow(low, int(settings["quadriflow_faces"])))
                reduction.append(
                    decimate(
                        low, ratio, str(settings.get("decimate_mode", "collapse")),
                        symmetry=bool(settings.get("decimate_symmetry", False)),
                        symmetry_axis=str(settings.get("symmetry_axis", "X")),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                warn(str(exc), warnings)

        if target_tris > 0:
            achieved = sum(triangle_count(obj) for obj in low_objects)
            report["target_tris"] = target_tris
            report["achieved_tris"] = achieved
            if abs(achieved - target_tris) > max(50, target_tris * 0.05):
                warn(
                    f"감면 결과 {achieved:,} 삼각형으로 목표 {target_tris:,}와 차이가 큽니다. "
                    "Decimate는 목표치를 근사하므로 --decimate로 미세 조정하세요.",
                    warnings,
                )
    else:
        low_objects = list(meshes)
        low_to_high = {}

    # 5) UV + 케이지 + 베이킹
    bake_results: dict[str, str] = {}
    if bake_types and low_objects:
        unwrap_method = str(settings.get("unwrap") or "auto")
        for low in low_objects:
            ensure_uv(low, unwrap_method, warnings)

        bake_dir_value = str(settings.get("bake_dir") or "").strip()
        bake_dir = Path(bake_dir_value).expanduser() if bake_dir_value else model.parent / "baked"
        size = int(settings.get("bake_size") or 2048)
        extrusion = float(settings.get("cage_extrusion") or 0.0)
        if extrusion <= 0:
            extrusion = max(world_dimensions(low_objects)) * 0.01 or 0.001  # 모델 크기의 1%
        samples = int(settings.get("bake_samples") or 32)

        if not reduction_mode and bake_types:
            warn(
                "감면된 로우폴리가 없습니다(경로 A). 이 경우 AO만 자기 베이크됩니다. "
                "경로 B라면 --target-tris 또는 --decimate를 함께 주세요.",
                warnings,
            )

        for low in low_objects:
            high = low_to_high.get(low.name, low) if reduction_mode else low
            cage = None
            if high is not low:
                cage = build_cage(low, extrusion, warnings)
            types = bake_types if high is not low else [kind for kind in bake_types if kind == "ao"]
            bake_results.update(
                bake_high_to_low(
                    low, high, bake_dir, size, types, margin=int(settings.get("bake_margin") or 8),
                    extrusion=extrusion, samples=samples, gpu=bool(settings.get("bake_gpu", False)),
                    cage=cage, warnings=warnings,
                )
            )
        report["bake"] = bake_results

        # 6) 베이킹 결과로 로우폴리 최종 머티리얼 재구성
        if bake_results and settings.get("materials", True):
            # 이전 실행에서 남은 맵이 섞이지 않도록 이번에 구운 슬롯만 쓴다.
            baked_slots = {"normal": "normal", "ao": "occlusion", "roughness": "roughness",
                           "basecolor": "basecolor", "metallic": "metallic"}
            allowed = {baked_slots[kind] for kind in bake_results if kind in baked_slots}
            found = discover_textures(bake_dir, stem=low_objects[0].name, warnings=warnings)
            baked_groups = {
                group: {slot: path for slot, path in slots.items() if slot in allowed}
                for group, slots in found.items()
            }
            final_materials = assign_materials(low_objects, baked_groups, options, warnings)
            report["final_materials"] = final_materials
            if "basecolor" not in bake_results:
                warn(
                    "basecolor를 베이킹하지 않아 로우폴리 최종 머티리얼에 색이 없습니다. "
                    "--bake normal,ao,roughness,basecolor 로 다시 베이크하거나 새로 텍스처링하세요.",
                    warnings,
                )

    # 7) 통계
    def stats(objects: list) -> list[dict]:
        return [
            {
                "name": obj.name,
                "triangles": triangle_count(obj),
                "vertices": len(obj.data.vertices),
                "uv_layers": [layer.name for layer in obj.data.uv_layers],
                "materials": [slot.material.name for slot in obj.material_slots if slot.material],
            }
            for obj in objects
        ]

    if reduction_mode:
        report["high"] = stats(high_objects)
    report["low"] = stats(low_objects)
    report["reduction"] = reduction
    report["triangles_total"] = sum(item["triangles"] for item in report["low"])

    # 8) 익스포트 (경로 B에서는 로우폴리만)
    export_objects = low_objects if retopo_mode else list(meshes)
    if settings.get("export_fbx"):
        report["export_fbx"] = export_fbx(Path(str(settings["export_fbx"])).expanduser(), export_objects, warnings)
    if settings.get("export_glb"):
        report["export_glb"] = export_glb(Path(str(settings["export_glb"])).expanduser(), export_objects, warnings)

    if retopo_mode and settings.get("drop_high"):
        for high in high_objects:
            if high in export_objects:
                continue
            try:
                bpy.data.objects.remove(high, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass

    # 9) .blend 저장 (텍스처 pack으로 경로 문제 방지)
    if settings.get("blend"):
        blend_path = Path(str(settings["blend"])).expanduser()
        blend_path.parent.mkdir(parents=True, exist_ok=True)
        if settings.get("pack_images", True):
            try:
                bpy.ops.file.pack_all()
            except Exception as exc:  # noqa: BLE001
                warn(f"이미지 pack 실패({exc}). .blend를 옮기면 텍스처 링크가 깨질 수 있습니다.", warnings)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
        report["blend"] = str(blend_path)
        log(f".blend 저장: {blend_path}")

    log(f"로우폴리 삼각형 합계 {report['triangles_total']:,}")
    if warnings:
        log(f"경고 {len(warnings)}건 - 리포트를 확인하세요")
    return report


# --------------------------------------------------------------------------- #
# 9) CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blender_import.py",
        description="AI 3D 에셋 임포트 -> PBR 머티리얼 -> 리토폴로지/감면 -> UV/케이지 -> Cycles 베이킹 -> 익스포트",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", required=True, help="GLB/glTF/FBX 경로")
    parser.add_argument("--textures", default="", help="텍스처 폴더 (기본: <모델 폴더>/textures)")
    parser.add_argument("--blend", default="", help="저장할 .blend 경로")
    parser.add_argument("--report", default="", help="JSON 리포트 경로 (기본: <모델 폴더>/blender_report.json)")
    parser.add_argument("--name", default="", help="에셋 기본 이름")
    parser.add_argument("--scale-target", type=float, default=0.0, help="최대 치수를 이 미터 값으로 정규화 (0=끔)")
    parser.add_argument("--origin", choices=["none", "bottom", "center"], default="none", help="원점 정리")
    parser.add_argument("--smooth-angle", type=float, default=30.0, help="스무스 각도(도). -1이면 플랫")
    parser.add_argument("--merge-distance", type=float, default=0.0001, help="중복 버텍스 병합 거리 (0=끔)")
    parser.add_argument("--recalc-normals", action="store_true", help="노멀을 바깥 방향으로 재계산")
    parser.add_argument("--target-tris", type=int, default=0, help="경로 B: 목표 삼각형 수 (예: 5000/10000/30000)")
    parser.add_argument("--decimate", type=float, default=0.0, help="경로 B: Decimate 비율 0~1 (예: 0.1)")
    parser.add_argument("--decimate-mode", choices=["collapse", "unsubdiv", "dissolve"], default="collapse")
    parser.add_argument("--decimate-symmetry", action="store_true", help="캐릭터 좌우 대칭 유지")
    parser.add_argument("--symmetry-axis", choices=["X", "Y", "Z"], default="X")
    parser.add_argument("--quadriflow-faces", type=int, default=0, help="Quadriflow 리메시 목표 면 수 (0=끔)")
    parser.add_argument("--voxel-size", type=float, default=0.0, help="Voxel Remesh 크기 (0=끔)")
    parser.add_argument("--unwrap", choices=["auto", "smart", "keep"], default="auto", help="로우폴리 UV 처리")
    parser.add_argument("--bake", default="", help="경로 B: 'normal,ao,roughness,basecolor,metallic' (빈 값=끔)")
    parser.add_argument("--bake-size", type=int, default=2048)
    parser.add_argument("--bake-dir", default="")
    parser.add_argument("--bake-samples", type=int, default=32)
    parser.add_argument("--bake-margin", type=int, default=8)
    parser.add_argument("--cage-extrusion", type=float, default=0.0, help="케이지 두께 (0=모델 크기 1%%)")
    parser.add_argument("--bake-gpu", action="store_true", help="Cycles GPU(OptiX) 사용")
    parser.add_argument("--ao-mode", choices=["multiply", "keep", "ignore"], default="multiply",
                        help="AO 처리: Base Color에 곱하기 / 노드만 두기 / 무시")
    parser.add_argument("--ao-strength", type=float, default=1.0)
    parser.add_argument("--normal-strength", type=float, default=1.0)
    parser.add_argument("--roughness-scale", type=float, default=1.0)
    parser.add_argument("--metallic-scale", type=float, default=1.0)
    parser.add_argument("--alpha", choices=["opaque", "clip", "blend"], default="opaque")
    parser.add_argument("--no-materials", action="store_true", help="머티리얼 재구성 생략")
    parser.add_argument("--export-fbx", default="")
    parser.add_argument("--export-glb", default="")
    parser.add_argument("--clear-scene", action="store_true", help="실행 전 씬의 모든 오브젝트 삭제")
    parser.add_argument("--drop-high", action="store_true", help="경로 B에서 베이킹 후 하이폴리 오브젝트 삭제")
    parser.add_argument("--no-pack", action="store_true", help=".blend 저장 시 이미지 pack 생략")
    return parser


def settings_from_args(args: argparse.Namespace) -> dict:
    return {
        "model": args.model,
        "textures": args.textures,
        "blend": args.blend,
        "name": args.name,
        "scale_target": args.scale_target,
        "origin": args.origin,
        "smooth_angle": args.smooth_angle,
        "merge_distance": args.merge_distance,
        "recalc_normals": args.recalc_normals,
        "target_tris": args.target_tris,
        "decimate": args.decimate,
        "decimate_mode": args.decimate_mode,
        "decimate_symmetry": args.decimate_symmetry,
        "symmetry_axis": args.symmetry_axis,
        "quadriflow_faces": args.quadriflow_faces,
        "voxel_size": args.voxel_size,
        "unwrap": args.unwrap,
        "bake": args.bake,
        "bake_size": args.bake_size,
        "bake_dir": args.bake_dir,
        "bake_samples": args.bake_samples,
        "bake_margin": args.bake_margin,
        "cage_extrusion": args.cage_extrusion,
        "bake_gpu": args.bake_gpu,
        "ao_mode": args.ao_mode,
        "ao_strength": args.ao_strength,
        "normal_strength": args.normal_strength,
        "roughness_scale": args.roughness_scale,
        "metallic_scale": args.metallic_scale,
        "alpha": args.alpha,
        "materials": not args.no_materials,
        "export_fbx": args.export_fbx,
        "export_glb": args.export_glb,
        "clear_scene": args.clear_scene,
        "drop_high": args.drop_high,
        "pack_images": not args.no_pack,
    }


def main(argv: list[str] | None = None) -> int:
    if bpy is None:
        print(LOG_PREFIX + "블렌더가 아닌 환경입니다. 이 파일은 Blender에서 실행하세요.", file=sys.stderr)
        return 2

    argv = list(sys.argv if argv is None else argv)
    extra = argv[argv.index("--") + 1:] if "--" in argv else []

    if extra:
        args = build_parser().parse_args(extra)
        settings = settings_from_args(args)
        report_path = Path(args.report).expanduser() if args.report else \
            Path(str(args.model)).expanduser().parent / "blender_report.json"
    else:
        if not SETTINGS.get("model"):
            log("SETTINGS['model']을 먼저 지정하세요. (헤드리스는 --model 인자 사용)")
            return 0
        settings = dict(SETTINGS)
        report_path = Path(str(settings.get("blend") or settings["model"])).expanduser()
        report_path = report_path.parent / "blender_report.json"

    report = run(settings)
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"리포트: {report_path}")
    except Exception as exc:  # noqa: BLE001
        warn(f"리포트 저장 실패: {exc}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 블렌더 로그에 전체 스택을 남긴다
        traceback.print_exc()
        sys.exit(1)
