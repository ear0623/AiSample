#!/usr/bin/env python3
"""AO / Roughness / Metallic 맵을 언리얼 엔진 표준 ORM 텍스처로 패킹하는 도구.

언리얼(그리고 glTF)은 세 장의 흑백 텍스처 대신 한 장의 RGB에 세 가지 마스크를
합쳐 쓰는 쪽이 표준이다. 채널 배치는 두 규격이 동일하다.

    R = Ambient Occlusion
    G = Roughness          (glTF metallicRoughnessTexture의 G와 같음)
    B = Metallic           (glTF metallicRoughnessTexture의 B와 같음)
    A = (사용 안 함, 필요하면 Opacity나 별도 마스크)

이 스크립트가 처리하는 것
  * 개별 AO/Roughness/Metallic 이미지 -> ORM 한 장
  * glTF 방식 metallic_roughness 한 장 -> ORM (AO는 별도 파일에서 R만 취함)
  * 채널별 해상도가 다를 때 리사이즈, 흑백 변환, 8bit PNG 출력
  * roughness/smoothness 규약 차이 보정(--invert-roughness)
  * 채널별 통계 출력으로 "정말 의도한 값이 들어갔는지" 검증

사용 예:
    # 개별 맵 3장 -> ORM
    python pipeline/texture_packer.py \
        --occlusion tex/ao.png --roughness tex/rough.png --metallic tex/metal.png \
        -o tex/T_Chair_ORM.png

    # glTF metallic_roughness + AO -> ORM
    python pipeline/texture_packer.py --metallic-roughness tex/mr.png --occlusion tex/ao.png \
        -o tex/T_Chair_ORM.png

    # 채널 검사만
    python pipeline/texture_packer.py --verify tex/T_Chair_ORM.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

DEFAULTS = {
    "occlusion": 255,  # AO 없음 = 가려짐 없음
    "roughness": 200,
    "metallic": 0,
}


class PackError(RuntimeError):
    """입력 텍스처를 읽을 수 없거나 규격이 맞지 않을 때."""


def _load_image(path: Path | str | None) -> Image.Image | None:
    """이미지를 연다. 경로가 None이면 None(호출부에서 기본값으로 채운다)."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        raise PackError(f"file not found: {p}")
    try:
        with Image.open(p) as im:
            im.load()
            return im.copy()
    except Exception as exc:  # noqa: BLE001 - Pillow 예외를 한 줄로 정리
        raise PackError(f"cannot read {p}: {exc}") from exc


def _load_gray(path: Path | str | None, default: int, size: tuple[int, int] | None) -> Image.Image:
    """이미지를 8bit 흑백(L)으로 읽는다. 경로가 None이면 균일한 기본값."""
    img = _load_image(path)
    if img is None:
        if size is None:
            raise PackError("size must be known before using default channels")
        return Image.new("L", size, default)
    return img.convert("L")


def _channel(img: Image.Image, index: int) -> Image.Image:
    """RGB(A) 이미지에서 한 채널을 L로 뽑는다."""
    bands = img.getbands()
    rgb = img.convert("RGB")
    return rgb.split()[index]


def resolve_inputs(
    occlusion: Path | None,
    roughness: Path | None,
    metallic: Path | None,
    metallic_roughness: Path | None,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """세 채널을 모두 L 이미지로 준비한다(해상도 통일 포함)."""
    rough_img: Image.Image | None = None
    metal_img: Image.Image | None = None
    ao_img: Image.Image | None = None

    mr = _load_image(metallic_roughness)
    if mr is not None:
        bands = mr.convert("RGB").split()
        rough_img = bands[1] if roughness is None else _load_image(roughness).convert("L")
        metal_img = bands[2] if metallic is None else _load_image(metallic).convert("L")
    else:
        if roughness is not None:
            rough_img = _load_image(roughness).convert("L")
        if metallic is not None:
            metal_img = _load_image(metallic).convert("L")

    ao_src = _load_image(occlusion)
    if ao_src is not None:
        if "A" in ao_src.getbands() and ao_src.getchannel("A").getextrema()[0] < 255:
            # 일부 생성기는 AO를 알파에 넣어 보낸다.
            ao_img = ao_src.getchannel("A")
        else:
            ao_img = ao_src.convert("L")

    known = [img for img in (ao_img, rough_img, metal_img) if img is not None]
    if not known:
        raise PackError("no input textures given")
    target = (max(img.width for img in known), max(img.height for img in known))

    def fit(img: Image.Image | None, default: int, name: str) -> Image.Image:
        if img is None:
            return Image.new("L", target, default)
        if img.size != target:
            print(f"[info] {name}: resized {img.size} -> {target}", file=sys.stderr)
            img = img.resize(target, Image.LANCZOS)
        return img

    ao = fit(ao_img, DEFAULTS["occlusion"], "occlusion")
    rough = fit(rough_img, DEFAULTS["roughness"], "roughness")
    metal = fit(metal_img, DEFAULTS["metallic"], "metallic")
    return ao, rough, metal


def pack_orm(
    occlusion: Path | str | None,
    roughness: Path | str | None,
    metallic: Path | str | None,
    out_path: Path | str,
    metallic_roughness: Path | str | None = None,
    invert_roughness: bool = False,
    invert_metallic: bool = False,
    invert_occlusion: bool = False,
) -> Path:
    """ORM 텍스처를 만들어 저장하고 경로를 돌려준다."""
    ao, rough, metal = resolve_inputs(
        Path(occlusion) if occlusion else None,
        Path(roughness) if roughness else None,
        Path(metallic) if metallic else None,
        Path(metallic_roughness) if metallic_roughness else None,
    )
    if invert_roughness:
        rough = rough.point(lambda v: 255 - v)
    if invert_metallic:
        metal = metal.point(lambda v: 255 - v)
    if invert_occlusion:
        ao = ao.point(lambda v: 255 - v)

    orm = Image.merge("RGB", (ao, rough, metal))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_path.suffix.lower()
    if suffix in (".tga",):
        orm.save(out_path, format="TGA")
    elif suffix in (".tif", ".tiff"):
        orm.save(out_path, format="TIFF", compression="tiff_lzw")
    else:
        if suffix != ".png":
            out_path = out_path.with_suffix(".png")
        orm.save(out_path, format="PNG", optimize=False)
    return out_path


def verify(path: Path | str) -> str:
    """ORM 텍스처의 채널별 통계로 채널 배치가 맞는지 확인한다."""
    p = Path(path)
    if not p.exists():
        raise PackError(f"file not found: {p}")
    with Image.open(p) as im:
        im.load()
        mode = im.mode
        rgb = im.convert("RGB")
        size = rgb.size
        names = ("R(AO)", "G(Rough)", "B(Metal)")
        stats = []
        for name, band in zip(names, rgb.split()):
            lo, hi = band.getextrema()
            hist = band.histogram()
            total = sum(hist) or 1
            mean = sum(i * n for i, n in enumerate(hist)) / total
            stats.append(f"  {name:<10} min={lo:3d} max={hi:3d} mean={mean:6.1f}")
    head = f"{p.name}  {size[0]}x{size[1]}  mode={mode}"
    return "\n".join([head, *stats])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AO/Roughness/Metallic를 UE5 ORM 텍스처로 패킹")
    parser.add_argument("--occlusion", "--ao", dest="occlusion", type=Path, help="AO 맵")
    parser.add_argument("--roughness", type=Path, help="Roughness 맵")
    parser.add_argument("--metallic", type=Path, help="Metallic 맵")
    parser.add_argument("--metallic-roughness", "-mr", type=Path, help="glTF 방식으로 이미 합쳐진 MR 맵(G=rough, B=metal)")
    parser.add_argument("-o", "--out", type=Path, help="출력 ORM 경로(.png)")
    parser.add_argument("--invert-roughness", action="store_true", help="smoothness로 저장된 맵이면 반전")
    parser.add_argument("--invert-metallic", action="store_true")
    parser.add_argument("--invert-occlusion", action="store_true")
    parser.add_argument("--verify", type=Path, metavar="ORM", help="기존 ORM 텍스처의 채널 통계만 출력")
    args = parser.parse_args(argv)

    if args.verify:
        print(verify(args.verify))
        return 0

    if not args.out:
        parser.error("-o/--out is required (or use --verify)")
    if args.metallic_roughness is None and args.roughness is None and args.metallic is None:
        parser.error("provide --metallic-roughness or at least one of --roughness/--metallic")

    try:
        path = pack_orm(
            occlusion=args.occlusion,
            roughness=args.roughness,
            metallic=args.metallic,
            out_path=args.out,
            metallic_roughness=args.metallic_roughness,
            invert_roughness=args.invert_roughness,
            invert_metallic=args.invert_metallic,
            invert_occlusion=args.invert_occlusion,
        )
    except PackError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(f"wrote {path}")
    print(verify(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
