#!/usr/bin/env python3
"""Tripo3D API로 고밀도 메시 + PBR 텍스처를 일괄 생성하는 파이프라인.

한 번의 실행으로 다음을 한다.

    1) 이미지/텍스트 -> 3D 생성 task 제출 (v3.1, Ultra 지오메트리 옵션)
    2) task 폴링
    3) GLB 다운로드
    4) GLB에 심어진 PBR 맵 추출 (basecolor / metallic_roughness / normal / occlusion)
    5) UE5 표준 ORM 텍스처 패킹 (R=AO, G=Roughness, B=Metallic)
    6) (선택) FBX + 분리 텍스처 zip으로 변환해 UE5 임포트용 폴더 구성
    7) manifest.json 기록

사용 예:
    export TRIPO_API_KEY=tsk_...

    # 레퍼런스 이미지 1장으로 고품질 에셋
    python pipeline/tripo_pbr_generator.py image refs/chair.png --name chair \
        --geometry-quality detailed --face-limit 2000000 --texture-quality detailed

    # 텍스트 프롬프트로
    python pipeline/tripo_pbr_generator.py text "a medieval wooden treasure chest" --name chest

    # 여러 개를 한 번에 (JSON 목록)
    python pipeline/tripo_pbr_generator.py batch assets.json

    # API를 부르지 않고 payload만 확인
    python pipeline/tripo_pbr_generator.py image refs/chair.png --name chair --dry-run

    # 이미 만든 task를 다시 조회
    python pipeline/tripo_pbr_generator.py status 123e4567-...
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# 스크립트로 직접 실행해도 패키지로 실행해도 동작하게 한다.
try:  # pragma: no cover - 실행 방식에 따라 갈린다
    from .glb_texture_tools import GlbError, describe, extract_textures
    from .texture_packer import PackError, pack_orm
    from .tripo_client import (
        DEFAULT_MODEL,
        TEXTURE_VERSION_V35,
        TripoClient,
        TripoError,
        build_convert_payload,
        build_image_payload,
        build_text_payload,
        dumps,
    )
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from glb_texture_tools import GlbError, describe, extract_textures
    from texture_packer import PackError, pack_orm
    from tripo_client import (
        DEFAULT_MODEL,
        TEXTURE_VERSION_V35,
        TripoClient,
        TripoError,
        build_convert_payload,
        build_image_payload,
        build_text_payload,
        dumps,
    )

DEFAULT_OUT_ROOT = Path("output")


# --------------------------------------------------------------------------- #
# 공통 유틸
# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    """에셋 이름을 폴더/파일명에 안전한 형태로."""
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", name.strip())
    slug = re.sub(r"_+", "_", slug).strip("_-")
    return slug or "asset"


def pascal(name: str) -> str:
    """UE5 에셋 이름 규칙(T_Chair_ORM)을 위한 PascalCase 변환."""
    parts = re.split(r"[^0-9A-Za-z가-힣]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "Asset"


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


@dataclass
class AssetJob:
    name: str
    image: str | None = None  # 로컬 경로 또는 http(s) URL
    prompt: str | None = None
    negative_prompt: str | None = None
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobOutcome:
    name: str
    ok: bool
    asset_dir: Path
    task_id: str | None = None
    credits: float | None = None
    files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


# --------------------------------------------------------------------------- #
# 텍스처 후처리
# --------------------------------------------------------------------------- #
def postprocess_textures(
    asset_dir: Path,
    texture_prefix: str,
    pack_orm_enabled: bool = True,
) -> tuple[dict[str, Path], list[str]]:
    """GLB에서 맵을 뽑고 ORM을 만든다. (생성된 파일, 경고) 반환."""
    warnings: list[str] = []
    tex_dir = asset_dir / "textures"
    written: dict[str, Path] = {}

    glb_path = asset_dir / "model.glb"
    if glb_path.exists():
        try:
            written = extract_textures(glb_path, tex_dir, prefix=texture_prefix)
        except GlbError as exc:
            warnings.append(f"texture extraction failed: {exc}")
    elif (asset_dir / "model.fbx").exists():
        warnings.append("FBX only: textures come from the convert step (ue5/ folder)")
    else:
        warnings.append("no model file found for texture extraction")

    if pack_orm_enabled and written:
        orm_name = f"{texture_prefix}ORM.png"
        try:
            mr = tex_dir / f"{texture_prefix}metallic_roughness.png"
            ao = tex_dir / f"{texture_prefix}occlusion.png"
            rough = tex_dir / f"{texture_prefix}roughness.png"
            metal = tex_dir / f"{texture_prefix}metallic.png"
            if mr.exists():
                orm_path = pack_orm(
                    occlusion=ao if ao.exists() else None,
                    roughness=None,
                    metallic=None,
                    out_path=tex_dir / orm_name,
                    metallic_roughness=mr,
                )
            elif rough.exists() or metal.exists():
                orm_path = pack_orm(
                    occlusion=ao if ao.exists() else None,
                    roughness=rough if rough.exists() else None,
                    metallic=metal if metal.exists() else None,
                    out_path=tex_dir / orm_name,
                )
            else:
                orm_path = None
            if orm_path:
                written["orm"] = orm_path
        except PackError as exc:
            warnings.append(f"ORM packing failed: {exc}")

        if not (tex_dir / f"{texture_prefix}occlusion.png").exists():
            warnings.append(
                "no AO map in the GLB: ORM R channel filled with 255 (no occlusion). "
                "Bake AO in Blender/DCC or generate it from the normal map for production."
            )
    return written, warnings


# --------------------------------------------------------------------------- #
# 엔진용 변환
# --------------------------------------------------------------------------- #
def convert_for_engine(
    client: TripoClient,
    task_id: str,
    asset_dir: Path,
    texture_size: int = 4096,
    face_limit: int | None = None,
    fbx_preset: str = "blender",
    timeout: float = 600.0,
    slug: str = "asset",
) -> tuple[dict[str, str], list[str]]:
    """FBX + 분리 텍스처(zip)로 변환해 ue5/ 폴더에 푼다."""
    warnings: list[str] = []
    files: dict[str, str] = {}
    payload = build_convert_payload(
        task_id,
        format="FBX",
        texture_size=texture_size,
        texture_format="PNG",
        fbx_preset=fbx_preset,
        texture_packaging="zip",
        face_limit=face_limit,
    )
    convert_task = client.convert_model(payload)
    result = client.wait(convert_task, timeout=timeout)
    if not result.model_url:
        warnings.append("convert task returned no model_url")
        return files, warnings

    ue5_dir = asset_dir / "ue5"
    ue5_dir.mkdir(parents=True, exist_ok=True)
    archive = ue5_dir / f"{slug}_fbx.zip"
    client.download(result.model_url, archive)

    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(ue5_dir)
        for member in sorted(ue5_dir.rglob("*")):
            if member.is_file() and member != archive:
                files[str(member.relative_to(asset_dir))] = "convert"
        archive.unlink(missing_ok=True)  # 압축은 풀었으니 남기지 않는다
    except zipfile.BadZipFile:
        # zip이 아니면 fbx 단일 파일로 저장
        target = ue5_dir / f"{slug}.fbx"
        shutil.move(str(archive), target)
        files[str(target.relative_to(asset_dir))] = "convert"
        warnings.append("convert output was not a zip; saved as a single FBX")
    return files, warnings


# --------------------------------------------------------------------------- #
# 한 에셋 처리
# --------------------------------------------------------------------------- #
def process_job(
    job: AssetJob,
    client: TripoClient | None,
    out_root: Path,
    args: argparse.Namespace,
) -> JobOutcome:
    slug = slugify(job.name)
    asset_dir = out_root / slug
    if not args.dry_run:
        asset_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = asset_dir / "manifest.json"
    texture_prefix = f"T_{pascal(job.name)}_"

    # 이미 성공한 에셋은 건너뛴다(--force로 재생성).
    if manifest_path.exists() and not args.force:
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        if previous.get("status") == "success":
            _say(f"{slug}: already done (manifest exists, use --force to regenerate)")
            return JobOutcome(
                name=job.name,
                ok=True,
                asset_dir=asset_dir,
                task_id=previous.get("task_id"),
                credits=previous.get("credits_consumed"),
                files=previous.get("files", {}),
            )

    overrides = dict(job.overrides)
    use_texture = not overrides.get("no_texture", args.no_texture)
    use_pbr = (not overrides.get("no_pbr", args.no_pbr)) and use_texture
    common: dict[str, Any] = {
        "model": overrides.get("model", args.model),
        "face_limit": overrides.get("face_limit", args.face_limit),
        "geometry_quality": overrides.get("geometry_quality", args.geometry_quality),
        "texture_quality": overrides.get("texture_quality", args.texture_quality),
        "texture_version": overrides.get("texture_version", args.texture_version),
        "pbr": use_pbr,
        "texture": use_texture,
        "delight": overrides.get("delight", args.delight),
        "auto_size": overrides.get("auto_size", args.auto_size),
        "texture_alignment": overrides.get("texture_alignment", args.texture_alignment),
        "model_seed": overrides.get("model_seed", args.model_seed),
        "texture_seed": overrides.get("texture_seed", args.texture_seed),
    }

    try:
        if job.image:
            image_input = str(job.image)
            is_url = image_input.startswith(("http://", "https://"))
            if args.dry_run:
                if not is_url:
                    image_input = f"<file_token of {Path(image_input).name}>"
            else:
                if not is_url and not Path(image_input).exists():
                    return JobOutcome(job.name, False, asset_dir, error=f"image not found: {image_input}")
                if not is_url:
                    # 로컬 파일은 먼저 업로드해서 file_token으로 바꾼다.
                    image_input = client.upload_file(image_input)  # type: ignore[union-attr]
            payload = build_image_payload(image_input, **common)
        else:
            payload = build_text_payload(job.prompt or "", job.negative_prompt, **common)
    except ValueError as exc:
        return JobOutcome(job.name, False, asset_dir, error=f"invalid options: {exc}")

    if args.dry_run:
        print(f"\n=== {slug} ===")
        print(dumps(payload))
        return JobOutcome(job.name, True, asset_dir, warnings=["dry-run: nothing sent"])

    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        assert client is not None
        if job.image:
            task_id = client.create_image_to_model(payload)
        else:
            task_id = client.create_text_to_model(payload)
        result = client.wait(task_id, timeout=args.timeout)
    except TripoError as exc:
        _say(f"{slug}: FAILED - {exc}")
        if exc.hint:
            _say(f"{slug}: hint - {exc.hint}")
        write_manifest(
            manifest_path,
            {
                "name": job.name,
                "slug": slug,
                "status": "failed",
                "started_at": started,
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "params": payload,
                "error": str(exc),
                "error_code": exc.code,
            },
        )
        return JobOutcome(job.name, False, asset_dir, error=str(exc))

    files: dict[str, str] = {}
    warnings: list[str] = []

    glb_path = asset_dir / "model.glb"
    if result.model_url:
        client.download(result.model_url, glb_path)
        files["model.glb"] = "generation"
    else:
        warnings.append("task succeeded but no model_url was returned")

    if result.preview_url:
        try:
            client.download(result.preview_url, asset_dir / "preview.png")
            files["preview.png"] = "generation"
        except Exception as exc:  # noqa: BLE001 - 미리보기는 실패해도 계속
            warnings.append(f"preview download failed: {exc}")

    if not args.no_textures and glb_path.exists():
        tex_files, tex_warnings = postprocess_textures(
            asset_dir, texture_prefix, pack_orm_enabled=not args.no_orm
        )
        warnings.extend(tex_warnings)
        for slot, path in tex_files.items():
            files[str(path.relative_to(asset_dir))] = f"texture:{slot}"

    if args.ue5 and result.task_id:
        try:
            ue5_files, ue5_warnings = convert_for_engine(
                client,
                result.task_id,
                asset_dir,
                texture_size=args.fbx_texture_size,
                face_limit=overrides.get("face_limit", args.face_limit),
                fbx_preset=args.fbx_preset,
                timeout=args.timeout,
                slug=slug,
            )
            files.update(ue5_files)
            warnings.extend(ue5_warnings)
        except TripoError as exc:
            warnings.append(f"FBX conversion failed: {exc}")

    manifest = {
        "name": job.name,
        "slug": slug,
        "status": "success",
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "task_id": result.task_id,
        "credits_consumed": result.credits_consumed,
        "model_url": result.model_url,
        "preview_url": result.preview_url,
        "params": payload,
        "files": files,
        "texture_prefix": texture_prefix,
        "warnings": warnings,
    }
    if glb_path.exists():
        try:
            manifest["glb"] = describe(glb_path)
        except GlbError:
            pass
    write_manifest(manifest_path, manifest)

    _say(f"{slug}: done -> {asset_dir}")
    for warning in warnings:
        _say(f"{slug}: note - {warning}")
    return JobOutcome(
        job.name,
        True,
        asset_dir,
        task_id=result.task_id,
        credits=result.credits_consumed,
        files=files,
        warnings=warnings,
    )


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 입력 파싱
# --------------------------------------------------------------------------- #
def load_batch(path: Path) -> list[AssetJob]:
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults: dict[str, Any] = {}
    items: Iterable[dict[str, Any]]
    if isinstance(data, dict):
        defaults = data.get("defaults", {}) or {}
        items = data.get("assets", [])
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("batch file must be a list or an object with 'assets'")

    jobs: list[AssetJob] = []
    base = path.parent
    for index, item in enumerate(items):
        name = item.get("name") or f"asset_{index:02d}"
        image = item.get("image")
        if image and not str(image).startswith(("http://", "https://")):
            candidate = Path(image)
            if not candidate.is_absolute() and not candidate.exists():
                candidate = base / candidate
            image = candidate
        job = AssetJob(
            name=name,
            image=str(image) if image else None,
            prompt=item.get("prompt"),
            negative_prompt=item.get("negative_prompt"),
            overrides={**defaults, **{k: v for k, v in item.items() if k not in ("name", "image", "prompt", "negative_prompt")}},
        )
        if not job.image and not job.prompt:
            raise ValueError(f"asset #{index} ('{name}') needs 'image' or 'prompt'")
        jobs.append(job)
    return jobs


def add_generation_args(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("생성 옵션")
    g.add_argument("--model", default=DEFAULT_MODEL, help=f"모델 버전 (기본 {DEFAULT_MODEL})")
    g.add_argument("--face-limit", type=int, default=None,
                   help="최대 삼각형 수. v3.1 Ultra 상한 2,000,000 / 게임 최적화는 50k~100k")
    g.add_argument("--geometry-quality", choices=["standard", "detailed"], default=None,
                   help="detailed = Ultra 모드(더 촘촘한 지오메트리)")
    g.add_argument("--texture-quality", choices=["fast", "standard", "detailed", "extreme"], default=None,
                   help="extreme = 8K 텍스처(크레딧 추가). fast는 texture-version v3.5 필요")
    g.add_argument("--texture-version", default=None,
                   help=f"텍스처 모델 고정 (예: {TEXTURE_VERSION_V35})")
    g.add_argument("--delight", dest="delight", action="store_true", default=None,
                   help="조명 베이킹 제거(기본 켜짐, v3.5 전용). --no-delight로 끔")
    g.add_argument("--no-delight", dest="delight", action="store_false")
    g.add_argument("--no-pbr", action="store_true", help="PBR 맵 없이 컬러 텍스처만")
    g.add_argument("--no-texture", action="store_true", help="텍스처 없이 지오메트리만")
    g.add_argument("--auto-size", action="store_true", help="실제 스케일(미터)로 정규화")
    g.add_argument("--texture-alignment", choices=["original_image", "geometry"], default=None)
    g.add_argument("--model-seed", type=int, default=None)
    g.add_argument("--texture-seed", type=int, default=None)

    p = parser.add_argument_group("출력/후처리")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_ROOT, help="출력 루트 (기본 ./output)")
    p.add_argument("--timeout", type=float, default=900.0, help="task 폴링 제한 시간(초)")
    p.add_argument("--no-textures", action="store_true", help="GLB 텍스처 추출 생략")
    p.add_argument("--no-orm", action="store_true", help="ORM 패킹 생략")
    p.add_argument("--ue5", action="store_true", help="FBX+분리 텍스처 zip으로 변환해 ue5/에 저장")
    p.add_argument("--fbx-texture-size", type=int, default=4096)
    p.add_argument("--fbx-preset", default="blender", choices=["blender", "3dsmax", "mixamo", "bake_scale"])
    p.add_argument("--force", action="store_true", help="성공한 에셋도 다시 생성")
    p.add_argument("--dry-run", action="store_true", help="API 호출 없이 payload만 출력")
    p.add_argument("--api-key", default=None, help="기본은 TRIPO_API_KEY 환경변수")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tripo3D API로 고품질 3D 에셋 + PBR 텍스처를 일괄 생성",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_image = sub.add_parser("image", help="이미지 -> 3D")
    p_image.add_argument("image", help="로컬 이미지 경로 또는 공개 URL")
    p_image.add_argument("--name", required=True, help="에셋 이름(폴더/텍스처 접두사에 사용)")
    add_generation_args(p_image)

    p_text = sub.add_parser("text", help="텍스트 -> 3D")
    p_text.add_argument("prompt")
    p_text.add_argument("--name", required=True)
    p_text.add_argument("--negative-prompt", default=None)
    add_generation_args(p_text)

    p_batch = sub.add_parser("batch", help="JSON 목록으로 여러 에셋 생성")
    p_batch.add_argument("file", type=Path)
    add_generation_args(p_batch)

    p_status = sub.add_parser("status", help="task 상태 조회")
    p_status.add_argument("task_id")
    p_status.add_argument("--api-key", default=None)

    args = parser.parse_args(argv)

    if args.command == "status":
        try:
            client = TripoClient(api_key=args.api_key)
            result = client.get_task(args.task_id)
        except TripoError as exc:
            print(f"[error] {exc}")
            return 1
        print(json.dumps({
            "task_id": result.task_id,
            "status": result.status,
            "progress": result.progress,
            "model_url": result.model_url,
            "credits_consumed": result.credits_consumed,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "image":
        jobs = [AssetJob(name=args.name, image=args.image)]
    elif args.command == "text":
        jobs = [AssetJob(name=args.name, prompt=args.prompt, negative_prompt=args.negative_prompt)]
    else:
        try:
            jobs = load_batch(args.file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[error] batch file: {exc}")
            return 2

    client: TripoClient | None = None
    if not args.dry_run:
        try:
            client = TripoClient(api_key=args.api_key)
        except TripoError as exc:
            print(f"[error] {exc}")
            return 1

    outcomes: list[JobOutcome] = []
    for job in jobs:
        outcomes.append(process_job(job, client, args.out, args))

    ok = [o for o in outcomes if o.ok]
    failed = [o for o in outcomes if not o.ok]
    print("\n=== 요약 ===")
    for outcome in outcomes:
        state = "OK" if outcome.ok else "FAIL"
        credits = f" credits={outcome.credits}" if outcome.credits is not None else ""
        error = f" - {outcome.error}" if outcome.error else ""
        print(f"[{state}] {outcome.name:<24} {outcome.asset_dir}{credits}{error}")
    if len(outcomes) > 1:
        print(f"\n{len(ok)} succeeded, {len(failed)} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
