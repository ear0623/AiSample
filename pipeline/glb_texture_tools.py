#!/usr/bin/env python3
"""GLB/glTF 파일에서 PBR 텍스처 맵을 꺼내는 도구.

AI 3D 생성 서비스(Tripo3D 등)는 보통 PBR 맵을 따로 주지 않고 하나의 GLB에
이미지로 심어서 준다. 엔진에서 쓰려면 먼저 맵을 슬롯별로 분리해야 하므로,
이 모듈은 GLB 바이너리를 직접 파싱해 다음을 뽑아낸다.

    basecolor.png            pbrMetallicRoughness.baseColorTexture
    metallic_roughness.png   pbrMetallicRoughness.metallicRoughnessTexture (G=rough, B=metal)
    normal.png               normalTexture
    occlusion.png            occlusionTexture
    emissive.png             emissiveTexture (있을 때만)
    roughness.png / metallic.png   metallic_roughness를 채널 분해한 결과

사용 예:
    python pipeline/glb_texture_tools.py extract output/chair/model.glb -o output/chair/textures
    python pipeline/glb_texture_tools.py info output/chair/model.glb

GLB 규격: 헤더 12바이트(magic, version, length) + 청크 반복(length, type, data).
외부 파일을 참조하는 .gltf(JSON)는 지원하지 않는다 — GLB 하나로 떨어지는
경우만 다루면 파이프라인에 충분하다.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GLB_MAGIC = 0x676C5446  # 'glTF'
CHUNK_JSON = 0x4E4F534A  # 'JSON'
CHUNK_BIN = 0x004E4942  # 'BIN\0'

# glTF 머티리얼 슬롯 -> 파일 접미사
SLOT_SUFFIX = {
    "basecolor": "basecolor",
    "metallic_roughness": "metallic_roughness",
    "normal": "normal",
    "occlusion": "occlusion",
    "emissive": "emissive",
}


class GlbError(RuntimeError):
    """GLB 파싱 실패."""


@dataclass
class GlbImage:
    index: int
    mime_type: str
    data: bytes
    name: str = ""
    source: str = "bufferView"  # "bufferView" | "uri"

    @property
    def extension(self) -> str:
        if "png" in self.mime_type:
            return ".png"
        if "jpeg" in self.mime_type or "jpg" in self.mime_type:
            return ".jpg"
        if "webp" in self.mime_type:
            return ".webp"
        return ".bin"


@dataclass
class Glb:
    path: Path
    gltf: dict[str, Any]
    bin_chunk: bytes
    images: list[GlbImage] = field(default_factory=list)

    @property
    def materials(self) -> list[dict[str, Any]]:
        return self.gltf.get("materials", []) or []

    @property
    def meshes(self) -> list[dict[str, Any]]:
        return self.gltf.get("meshes", []) or []

    def triangle_count(self) -> int | None:
        """메시별 인덱스 개수로 삼각형 수를 추정한다(정확도는 exporter에 따라 다름)."""
        accessors = self.gltf.get("accessors", []) or []
        total = 0
        found = False
        for mesh in self.meshes:
            for prim in mesh.get("primitives", []) or []:
                idx = prim.get("indices")
                mode = prim.get("mode", 4)  # 4 = TRIANGLES
                if idx is not None and idx < len(accessors) and mode == 4:
                    count = accessors[idx].get("count", 0)
                    total += count // 3
                    found = True
        return total if found else None


# --------------------------------------------------------------------------- #
# GLB 파싱
# --------------------------------------------------------------------------- #
def read_glb(path: str | Path) -> Glb:
    path = Path(path)
    blob = path.read_bytes()
    if len(blob) < 12:
        raise GlbError(f"{path} is too small to be a GLB file")

    magic, version, total_length = struct.unpack_from("<III", blob, 0)
    if magic != GLB_MAGIC:
        raise GlbError(f"{path} is not a GLB file (bad magic: {magic:#x}); .gltf + external files is not supported")
    if version != 2:
        raise GlbError(f"unsupported GLB version {version} (only 2 is supported)")
    if total_length != len(blob):
        # 잘린 파일이거나 뒤에 여분이 붙은 경우. 파싱은 계속하되 알린다.
        print(f"[warn] header length {total_length} != file size {len(blob)}: file may be truncated", file=sys.stderr)

    offset = 12
    gltf: dict[str, Any] | None = None
    bin_chunk = b""
    while offset + 8 <= len(blob):
        chunk_len, chunk_type = struct.unpack_from("<II", blob, offset)
        offset += 8
        data = blob[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type == CHUNK_JSON:
            gltf = json.loads(data.decode("utf-8").rstrip("\x00 "))
        elif chunk_type == CHUNK_BIN:
            bin_chunk = data

    if gltf is None:
        raise GlbError(f"{path}: no JSON chunk found")

    glb = Glb(path=path, gltf=gltf, bin_chunk=bin_chunk)
    glb.images = list(iter_images(glb))
    return glb


def iter_images(glb: Glb) -> list[GlbImage]:
    """glTF images[]를 실제 바이트로 변환한다."""
    out: list[GlbImage] = []
    buffer_views = glb.gltf.get("bufferViews", []) or []
    buffers = glb.gltf.get("buffers", []) or []

    for i, img in enumerate(glb.gltf.get("images", []) or []):
        name = img.get("name", "") or ""
        if "bufferView" in img:
            bv_index = img["bufferView"]
            if bv_index >= len(buffer_views):
                raise GlbError(f"image[{i}] references missing bufferView {bv_index}")
            bv = buffer_views[bv_index]
            buf_index = bv.get("buffer", 0)
            if buf_index >= len(buffers):
                raise GlbError(f"bufferView {bv_index} references missing buffer {buf_index}")
            start = bv.get("byteOffset", 0)
            length = bv.get("byteLength", 0)
            data = glb.bin_chunk[start : start + length]
            if not data:
                raise GlbError(
                    f"image[{i}] has no data in the GLB BIN chunk "
                    f"(buffer {buf_index} may be external)"
                )
            out.append(
                GlbImage(
                    index=i,
                    mime_type=img.get("mimeType", "image/png"),
                    data=data,
                    name=name,
                    source="bufferView",
                )
            )
        elif "uri" in img:
            uri = img["uri"]
            if uri.startswith("data:"):
                header, _, payload = uri.partition(",")
                mime = header[5:].split(";")[0] if header.startswith("data:") else "image/png"
                out.append(
                    GlbImage(
                        index=i,
                        mime_type=mime,
                        data=base64.b64decode(payload),
                        name=name,
                        source="uri",
                    )
                )
            else:
                # 외부 파일 참조: GLB 옆에 있다면 읽어준다.
                candidate = Path(glb.path).parent / uri
                if candidate.exists():
                    mime = "image/png" if candidate.suffix.lower() == ".png" else "image/jpeg"
                    out.append(
                        GlbImage(
                            index=i,
                            mime_type=mime,
                            data=candidate.read_bytes(),
                            name=name or candidate.stem,
                            source=f"file:{uri}",
                        )
                    )
                else:
                    print(f"[warn] image[{i}] uri '{uri}' not found next to {glb.path.name}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- #
# 머티리얼 슬롯 매핑
# --------------------------------------------------------------------------- #
def _texture_to_image(glb: Glb, texture_index: int) -> GlbImage | None:
    textures = glb.gltf.get("textures", []) or []
    if not (0 <= texture_index < len(textures)):
        return None
    source = textures[texture_index].get("source")
    if source is None:
        # KHR_texture_basisu 등 확장 슬롯: extensions.source 시도
        ext = textures[texture_index].get("extensions", {}) or {}
        for value in ext.values():
            if isinstance(value, dict) and "source" in value:
                source = value["source"]
                break
    if source is None:
        return None
    for img in glb.images:
        if img.index == source:
            return img
    return None


def material_slots(glb: Glb) -> dict[str, GlbImage]:
    """머티리얼별 슬롯 -> 이미지. 머티리얼이 여러 개면 'm1_...' 접두사를 붙인다."""
    slots: dict[str, GlbImage] = {}
    materials = glb.materials
    multiple = len(materials) > 1

    for m_index, mat in enumerate(materials):
        prefix = f"m{m_index}_" if multiple else ""
        mat_name = (mat.get("name") or f"material{m_index}").replace(" ", "_")

        pbr = mat.get("pbrMetallicRoughness", {}) or {}
        found = [
            ("basecolor", pbr.get("baseColorTexture")),
            ("metallic_roughness", pbr.get("metallicRoughnessTexture")),
            ("normal", mat.get("normalTexture")),
            ("occlusion", mat.get("occlusionTexture")),
            ("emissive", mat.get("emissiveTexture")),
        ]
        for slot, tex in found:
            if not tex:
                continue
            image = _texture_to_image(glb, tex.get("index", -1))
            if image is None:
                print(f"[warn] {mat_name}.{slot}: texture index missing", file=sys.stderr)
                continue
            key = f"{prefix}{slot}"
            if key not in slots:
                slots[key] = image

        # 확장 슬롯(스펙 외 PBR 확장)이 있으면 이름만 남겨 알린다.
        ext = mat.get("extensions", {}) or {}
        for ext_name in ext:
            if ext_name in {"KHR_materials_pbrSpecularGlossiness", "KHR_materials_unlit"}:
                print(f"[warn] {mat_name}: material extension {ext_name} - base color만 신뢰할 것", file=sys.stderr)

    if not slots and glb.images:
        # 머티리얼 매핑이 깨진 파일: 이미지 순서대로 저장한다.
        print("[warn] no material texture slots found; saving images by index", file=sys.stderr)
        for img in glb.images:
            slots[f"image{img.index}"] = img
    return slots


# --------------------------------------------------------------------------- #
# 추출
# --------------------------------------------------------------------------- #
def extract_textures(
    glb_path: str | Path,
    out_dir: str | Path,
    prefix: str = "",
    split_metallic_roughness: bool = True,
    overwrite: bool = True,
) -> dict[str, Path]:
    """GLB에서 PBR 맵을 PNG로 추출한다. {슬롯: 저장 경로}를 돌려준다."""
    from PIL import Image
    import io

    glb = read_glb(glb_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slots = material_slots(glb)
    written: dict[str, Path] = {}

    for slot, image in slots.items():
        stem = f"{prefix}{SLOT_SUFFIX.get(slot, slot)}"
        target = out_dir / f"{stem}.png"
        if target.exists() and not overwrite:
            written[slot] = target
            continue
        img = Image.open(io.BytesIO(image.data))
        img.load()
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        img.save(target, format="PNG", optimize=False)
        written[slot] = target

        if split_metallic_roughness and slot.endswith("metallic_roughness"):
            base = Path(stem.rsplit("metallic_roughness", 1)[0]) if "metallic_roughness" in stem else Path(stem)
            mr = img.convert("RGB")
            r_ch, g_ch, b_ch = mr.split()
            rough_path = out_dir / f"{prefix}roughness.png"
            metal_path = out_dir / f"{prefix}metallic.png"
            g_ch.save(rough_path, format="PNG")
            b_ch.save(metal_path, format="PNG")
            written[slot.replace("metallic_roughness", "roughness")] = rough_path
            written[slot.replace("metallic_roughness", "metallic")] = metal_path
            del r_ch  # glTF metallicRoughness의 R은 미사용

    if not written:
        raise GlbError(f"{glb_path}: no textures found in the GLB")
    return written


def describe(glb_path: str | Path) -> str:
    glb = read_glb(glb_path)
    lines = [f"file: {Path(glb_path).name}", f"materials: {len(glb.materials)}", f"images: {len(glb.images)}"]
    tris = glb.triangle_count()
    if tris is not None:
        lines.append(f"triangles(approx): {tris:,}")
    for i, mat in enumerate(glb.materials):
        pbr = mat.get("pbrMetallicRoughness", {}) or {}
        factors = []
        if "baseColorFactor" in pbr:
            factors.append("baseColorFactor=" + ",".join(f"{v:.2f}" for v in pbr["baseColorFactor"]))
        if "metallicFactor" in pbr:
            factors.append(f"metallicFactor={pbr['metallicFactor']}")
        if "roughnessFactor" in pbr:
            factors.append(f"roughnessFactor={pbr['roughnessFactor']}")
        lines.append(f"  material[{i}] {mat.get('name', '')}: {' '.join(factors) or '-'}")
    for slot, image in material_slots(glb).items():
        from PIL import Image
        import io

        size = "?"
        try:
            with Image.open(io.BytesIO(image.data)) as im:
                size = f"{im.width}x{im.height} {im.mode}"
        except Exception:  # pragma: no cover - 손상된 이미지
            pass
        lines.append(f"  {slot:<24} image[{image.index}] {image.mime_type:<10} {size}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GLB에서 PBR 텍스처 맵을 추출한다")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="PBR 맵을 PNG로 저장")
    p_extract.add_argument("glb", type=Path)
    p_extract.add_argument("-o", "--out", type=Path, required=True)
    p_extract.add_argument("--prefix", default="", help="출력 파일 접두사 (예: T_Chair_)")
    p_extract.add_argument("--no-split-mr", action="store_true", help="metallic_roughness를 roughness/metallic로 분해하지 않음")

    p_info = sub.add_parser("info", help="GLB 구성 요약")
    p_info.add_argument("glb", type=Path)

    args = parser.parse_args(argv)
    if args.command == "info":
        print(describe(args.glb))
        return 0

    written = extract_textures(
        args.glb,
        args.out,
        prefix=args.prefix,
        split_metallic_roughness=not args.no_split_mr,
    )
    for slot, path in written.items():
        print(f"{slot:<24} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
