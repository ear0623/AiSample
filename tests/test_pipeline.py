"""파이프라인 핵심 로직 테스트 (네트워크·API 키 없이 실행).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.glb_texture_tools import (  # noqa: E402
    GlbError,
    describe,
    extract_textures,
    read_glb,
)
from pipeline.texture_packer import PackError, pack_orm, verify  # noqa: E402
from pipeline.tripo_client import (  # noqa: E402
    TEXTURE_VERSION_V35,
    TripoClient,
    TripoError,
    build_convert_payload,
    build_image_payload,
    build_text_payload,
)
import pipeline.tripo_pbr_generator as gen  # noqa: E402


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #
def png_bytes(color: tuple[int, ...], size: tuple[int, int] = (8, 8), mode: str = "RGB") -> bytes:
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_glb(images: list[tuple[str, bytes]], material: dict | None = None) -> bytes:
    """테스트용 최소 GLB를 만든다 (이미지는 bufferView에 심는다)."""
    bin_parts: list[bytes] = []
    views: list[dict] = []
    offset = 0
    for name, data in images:
        padded = data + b"\x00" * (-len(data) % 4)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        bin_parts.append(padded)
        offset += len(padded)

    bin_chunk = b"".join(bin_parts)
    gltf = {
        "asset": {"version": "2.0", "generator": "test"},
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": views,
        "images": [
            {"bufferView": i, "mimeType": "image/png", "name": name}
            for i, (name, _) in enumerate(images)
        ],
        "textures": [{"source": i} for i in range(len(images))],
        "materials": [material] if material else [],
        "meshes": [{"primitives": [{"attributes": {}}]}],
    }
    json_chunk = json.dumps(gltf).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)

    body = struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    body += struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk
    header = struct.pack("<III", 0x676C5446, 2, 12 + len(body))
    return header + body


STANDARD_MATERIAL = {
    "name": "mat",
    "pbrMetallicRoughness": {
        "baseColorTexture": {"index": 0},
        "metallicRoughnessTexture": {"index": 1},
    },
    "normalTexture": {"index": 2},
    "occlusionTexture": {"index": 3},
}


class GlbTextureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # basecolor=(10,20,30), MR=(0,128,0), normal=(128,128,255), occlusion=(200,200,200)
        glb = build_glb(
            [
                ("basecolor", png_bytes((10, 20, 30))),
                ("metallic_roughness", png_bytes((0, 128, 0))),
                ("normal", png_bytes((128, 128, 255))),
                ("occlusion", png_bytes((200, 200, 200))),
            ],
            STANDARD_MATERIAL,
        )
        self.glb_path = self.dir / "model.glb"
        self.glb_path.write_bytes(glb)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_read_glb(self) -> None:
        glb = read_glb(self.glb_path)
        self.assertEqual(len(glb.images), 4)
        self.assertEqual(len(glb.materials), 1)

    def test_extract_slots_and_channels(self) -> None:
        out = self.dir / "textures"
        written = extract_textures(self.glb_path, out)
        self.assertIn("basecolor", written)
        self.assertIn("metallic_roughness", written)
        self.assertIn("normal", written)
        self.assertIn("occlusion", written)

        with Image.open(written["basecolor"]) as im:
            self.assertEqual(im.convert("RGB").getpixel((0, 0)), (10, 20, 30))
        # glTF 규격: G=roughness, B=metallic
        with Image.open(written["roughness"]) as im:
            self.assertEqual(im.convert("L").getpixel((0, 0)), 128)
        with Image.open(written["metallic"]) as im:
            self.assertEqual(im.convert("L").getpixel((0, 0)), 0)
        with Image.open(written["occlusion"]) as im:
            self.assertEqual(im.convert("L").getpixel((0, 0)), 200)

    def test_extract_prefix(self) -> None:
        written = extract_textures(self.glb_path, self.dir / "t", prefix="T_Chair_")
        self.assertTrue(all(p.name.startswith("T_Chair_") for p in written.values()))

    def test_describe_runs(self) -> None:
        text = describe(self.glb_path)
        self.assertIn("materials: 1", text)
        self.assertIn("basecolor", text)

    def test_invalid_file(self) -> None:
        bad = self.dir / "bad.glb"
        bad.write_bytes(b"not a glb at all")
        with self.assertRaises(GlbError):
            read_glb(bad)

    def test_material_without_textures_falls_back_to_index(self) -> None:
        glb = build_glb([("a", png_bytes((1, 2, 3))), ("b", png_bytes((4, 5, 6)))], {"name": "empty"})
        path = self.dir / "no_slots.glb"
        path.write_bytes(glb)
        written = extract_textures(path, self.dir / "fallback")
        self.assertIn("image0", written)
        self.assertIn("image1", written)


class TexturePackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, color: tuple[int, ...]) -> Path:
        path = self.dir / name
        Image.new("L", (4, 4), color[0]).save(path)
        return path

    def test_pack_individual_maps(self) -> None:
        ao = self._write("ao.png", (255,))
        rough = self._write("rough.png", (90,))
        metal = self._write("metal.png", (255,))
        out = pack_orm(ao, rough, metal, self.dir / "orm.png")
        with Image.open(out) as im:
            self.assertEqual(im.mode, "RGB")
            self.assertEqual(im.getpixel((0, 0)), (255, 90, 255))

    def test_pack_from_gltf_mr_with_default_ao(self) -> None:
        mr = self.dir / "mr.png"
        Image.new("RGB", (4, 4), (0, 128, 64)).save(mr)
        out = pack_orm(None, None, None, self.dir / "orm.png", metallic_roughness=mr)
        with Image.open(out) as im:
            self.assertEqual(im.getpixel((0, 0)), (255, 128, 64))

    def test_invert_roughness(self) -> None:
        rough = self._write("rough.png", (30,))
        out = pack_orm(None, rough, None, self.dir / "orm.png", invert_roughness=True)
        with Image.open(out) as im:
            self.assertEqual(im.getpixel((0, 0))[1], 225)

    def test_resizes_mismatched_inputs(self) -> None:
        ao = self.dir / "ao.png"
        Image.new("L", (8, 8), 200).save(ao)
        rough = self.dir / "r.png"
        Image.new("L", (4, 4), 100).save(rough)
        out = pack_orm(ao, rough, None, self.dir / "orm.png")
        with Image.open(out) as im:
            self.assertEqual(im.size, (8, 8))

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(PackError):
            pack_orm(self.dir / "nope.png", None, None, self.dir / "orm.png")

    def test_verify_reports_channels(self) -> None:
        mr = self.dir / "mr.png"
        Image.new("RGB", (2, 2), (0, 10, 20)).save(mr)
        out = pack_orm(None, None, None, self.dir / "orm.png", metallic_roughness=mr)
        text = verify(out)
        self.assertIn("R(AO)", text)
        self.assertIn("G(Rough)", text)
        self.assertIn("B(Metal)", text)


class PayloadTests(unittest.TestCase):
    def test_text_payload_defaults(self) -> None:
        payload = build_text_payload("a chair", texture_version=TEXTURE_VERSION_V35, delight=True)
        self.assertEqual(payload["model"], "v3.1-20260211")
        self.assertTrue(payload["pbr"])
        self.assertTrue(payload["texture"])
        self.assertEqual(payload["texture_version"], TEXTURE_VERSION_V35)

    def test_ultra_geometry_and_face_limit(self) -> None:
        payload = build_image_payload(
            "file_abc", geometry_quality="detailed", face_limit=2_000_000, texture_quality="detailed"
        )
        self.assertEqual(payload["geometry_quality"], "detailed")
        self.assertEqual(payload["face_limit"], 2_000_000)
        self.assertEqual(payload["texture_quality"], "detailed")

    def test_fast_texture_requires_v35(self) -> None:
        with self.assertRaises(ValueError):
            build_text_payload("x", texture_quality="fast")

    def test_delight_requires_v35(self) -> None:
        with self.assertRaises(ValueError):
            build_text_payload("x", delight=True)

    def test_geometry_quality_rejected_on_v25(self) -> None:
        with self.assertRaises(ValueError):
            build_text_payload("x", model="v2.5-20250123", geometry_quality="detailed")

    def test_pbr_requires_texture(self) -> None:
        with self.assertRaises(ValueError):
            build_text_payload("x", texture=False, pbr=True)

    def test_convert_payload_for_ue5(self) -> None:
        payload = build_convert_payload("task-123", format="fbx", texture_size=2048)
        self.assertEqual(payload["format"], "FBX")
        self.assertEqual(payload["texture_packaging"], "zip")
        self.assertEqual(payload["texture_size"], 2048)
        self.assertTrue(payload["bake"])

    def test_naming_helpers(self) -> None:
        self.assertEqual(gen.slugify("Wooden Chair #1"), "Wooden_Chair_1")
        self.assertEqual(gen.pascal("wooden chair 01"), "WoodenChair01")


# --------------------------------------------------------------------------- #
# 네트워크 계층 (가짜 세션)
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, status: int = 200, payload: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_content(self, chunk_size: int = 1):  # noqa: D401
        yield b"data"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class FakeSession:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple] = []

    def request(self, method, url, **kwargs):
        self.calls.append(("request", method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ClientTests(unittest.TestCase):
    def make_client(self, responses: list) -> tuple[TripoClient, FakeSession]:
        session = FakeSession(responses)
        client = TripoClient(api_key="test-key", session=session, verbose=False)
        return client, session

    def test_get_task_success(self) -> None:
        client, _ = self.make_client(
            [
                FakeResponse(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "task_id": "t1",
                            "status": "success",
                            "progress": 100,
                            "output": {"model_url": "https://cdn/model.glb"},
                            "credits_consumed": 12.5,
                        },
                    },
                )
            ]
        )
        result = client.get_task("t1")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.model_url, "https://cdn/model.glb")
        self.assertEqual(result.credits_consumed, 12.5)

    def test_api_error_code_raises_with_hint(self) -> None:
        client, _ = self.make_client(
            [FakeResponse(200, {"code": 1004, "message": "invalid parameter"})]
        )
        with self.assertRaises(TripoError) as ctx:
            client.get_task("t1")
        self.assertEqual(ctx.exception.code, 1004)
        self.assertIn("1004", ctx.exception.hint or "")

    def test_retry_on_429_then_success(self) -> None:
        client, session = self.make_client(
            [
                FakeResponse(429, {"code": 429, "message": "rate limited"}, headers={"Retry-After": "0"}),
                FakeResponse(200, {"code": 0, "data": {"task_id": "t2", "status": "running", "progress": 10}}),
            ]
        )
        with mock.patch("pipeline.tripo_client.time.sleep"):
            result = client.get_task("t2")
        self.assertEqual(result.progress, 10)
        self.assertEqual(len(session.calls), 2)

    def test_http_401_hint(self) -> None:
        client, _ = self.make_client([FakeResponse(401, {"message": "unauthorized"})])
        with self.assertRaises(TripoError) as ctx:
            client.get_task("t")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("API 키", ctx.exception.hint or "")

    def test_wait_polls_until_success(self) -> None:
        client, session = self.make_client(
            [
                FakeResponse(200, {"code": 0, "data": {"task_id": "t3", "status": "running", "progress": 30}}),
                FakeResponse(
                    200,
                    {"code": 0, "data": {"task_id": "t3", "status": "success", "progress": 100,
                                          "output": {"model_url": "https://cdn/m.glb"}}},
                ),
            ]
        )
        with mock.patch("pipeline.tripo_client.time.sleep"):
            result = client.wait("t3", timeout=5, interval=0.01)
        self.assertEqual(result.status, "success")
        self.assertEqual(len(session.calls), 2)

    def test_wait_raises_on_failure(self) -> None:
        client, _ = self.make_client(
            [FakeResponse(200, {"code": 0, "data": {"task_id": "t4", "status": "failed", "progress": 40,
                                                     "error_code": 2001, "error_message": "bad input"}})]
        )
        with self.assertRaises(TripoError) as ctx:
            client.wait("t4", timeout=5, interval=0.01)
        self.assertIn("failed", str(ctx.exception))

    def test_download_writes_file(self) -> None:
        client, _ = self.make_client([FakeResponse(200, None)])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "model.glb"
            client.download("https://cdn/m.glb", target)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_bytes(), b"data")


if __name__ == "__main__":
    unittest.main()
