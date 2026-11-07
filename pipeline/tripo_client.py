#!/usr/bin/env python3
"""Tripo3D OpenAPI(v3) 클라이언트.

공식 문서: https://developers.tripo3d.ai/en/docs
Base URL: https://openapi.tripo3d.ai/v3

이 모듈은 HTTP·재시도·폴링만 담당하고, 어떤 옵션을 쓸지 결정하는 정책은
`tripo_pbr_generator.py`에 둔다. payload를 만드는 함수는 순수 함수라서
API 키 없이도 테스트할 수 있다.

주의해서 구현한 부분
  * 생성 API는 비동기다. POST는 task_id만 주고, 결과는 GET /tasks/{id}로 폴링한다.
  * HTTP 200이어도 body의 code가 0이 아니면 실패다(예: 1004 파라미터 오류).
  * 텍스처 품질 `fast`와 `delight`는 texture_version=v3.5-20260815에서만 동작한다.
  * 429/5xx는 지수 백오프로 재시도하되 Retry-After를 존중한다.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

BASE_URL = "https://openapi.tripo3d.ai/v3"
DEFAULT_MODEL = "v3.1-20260211"
TEXTURE_VERSION_V35 = "v3.5-20260815"

TERMINAL_SUCCESS = "success"
TERMINAL_FAILURES = {"failed", "cancelled", "banned", "expired"}


class TripoError(RuntimeError):
    """API 호출 실패. code/status/payload에 원인을 담는다."""

    def __init__(
        self,
        message: str,
        code: int | None = None,
        status: int | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.payload = dict(payload or {})

    @property
    def hint(self) -> str | None:
        if self.status in (401, 403):
            return "API 키를 확인하세요. TRIPO_API_KEY 환경변수 또는 --api-key."
        if self.code == 1004:
            return "파라미터 조합이 거부되었습니다(1004). texture_quality=fast/delight는 texture_version=v3.5-20260815가 필요합니다."
        if self.status == 429:
            return "요청 한도에 걸렸습니다. 잠시 후 재시도하거나 --timeout을 늘리세요."
        if self.status and self.status >= 500:
            return "서버 오류입니다. 잠시 후 재시도하세요."
        return None


@dataclass
class TaskResult:
    task_id: str
    status: str
    progress: int
    output: dict[str, Any]
    credits_consumed: float | None = None
    error_code: int | None = None
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def model_url(self) -> str | None:
        return (self.output or {}).get("model_url")

    @property
    def preview_url(self) -> str | None:
        return (self.output or {}).get("rendered_image_url")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TaskResult":
        return cls(
            task_id=str(payload.get("task_id", "")),
            status=str(payload.get("status", "unknown")),
            progress=int(payload.get("progress", 0) or 0),
            output=dict(payload.get("output", {}) or {}),
            credits_consumed=payload.get("credits_consumed"),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
            created_at=payload.get("created_at"),
            completed_at=payload.get("completed_at"),
            raw=dict(payload),
        )


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class TripoClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 60.0,
        max_retries: int = 4,
        session: requests.Session | None = None,
        verbose: bool = True,
    ) -> None:
        key = api_key or os.environ.get("TRIPO_API_KEY", "").strip()
        if not key:
            raise TripoError("TRIPO_API_KEY is not set. export TRIPO_API_KEY=tsk_... or pass --api-key.")
        self._api_key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.verbose = verbose

    # ------------------------------------------------------------------ #
    # 저수준 요청
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _request(
        self,
        method: str,
        path: str,
        json_body: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        expect_json: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:  # 연결 실패, 타임아웃
                last_error = exc
                wait = self._backoff(attempt)
                if attempt < self.max_retries:
                    _log(f"network error ({exc.__class__.__name__}), retry in {wait:.1f}s")
                    time.sleep(wait)
                    continue
                raise TripoError(f"network error talking to {url}: {exc}") from exc

            if response.status_code == 429 or response.status_code >= 500:
                wait = self._retry_after(response) or self._backoff(attempt)
                if attempt < self.max_retries:
                    _log(f"HTTP {response.status_code}, retry in {wait:.1f}s")
                    time.sleep(wait)
                    continue
                raise TripoError(
                    f"HTTP {response.status_code} from {path}",
                    status=response.status_code,
                )

            if response.status_code >= 400:
                payload: dict[str, Any] = {}
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"raw": response.text[:500]}
                raise TripoError(
                    f"HTTP {response.status_code} from {path}: {payload.get('message') or response.text[:300]}",
                    code=payload.get("code"),
                    status=response.status_code,
                    payload=payload,
                )

            if not expect_json:
                return {"raw": response.content}

            try:
                body = response.json()
            except ValueError as exc:
                raise TripoError(f"invalid JSON from {path}: {response.text[:300]}") from exc

            code = body.get("code")
            if code not in (0, None):
                raise TripoError(
                    f"API error {code}: {body.get('message', '(no message)')}",
                    code=code,
                    status=response.status_code,
                    payload=body,
                )
            return body

        raise TripoError(f"request failed after retries: {last_error}")

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = min(2 ** attempt, 30)
        return base + random.uniform(0, 0.75)

    @staticmethod
    def _retry_after(response: requests.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # 파일 업로드
    # ------------------------------------------------------------------ #
    def upload_file(self, path: str | Path) -> str:
        path = Path(path)
        if not path.exists():
            raise TripoError(f"upload file not found: {path}")
        if path.stat().st_size > 20 * 1024 * 1024 and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            raise TripoError(f"image {path.name} is larger than 20 MB; resize it first")
        _log(f"uploading {path.name} ({path.stat().st_size / 1024:.0f} KB)")
        with path.open("rb") as handle:
            body = self._request("POST", "/files", files={"file": (path.name, handle)})
        token = (body.get("data") or {}).get("file_token")
        if not token:
            raise TripoError("upload did not return file_token", payload=body)
        return str(token)

    # ------------------------------------------------------------------ #
    # 생성
    # ------------------------------------------------------------------ #
    def create_text_to_model(self, payload: Mapping[str, Any]) -> str:
        return self._create("/generation/text-to-model", payload)

    def create_image_to_model(self, payload: Mapping[str, Any]) -> str:
        return self._create("/generation/image-to-model", payload)

    def convert_model(self, payload: Mapping[str, Any]) -> str:
        return self._create("/models/convert", payload)

    def _create(self, path: str, payload: Mapping[str, Any]) -> str:
        body = self._request("POST", path, json_body=payload)
        task_id = (body.get("data") or {}).get("task_id")
        if not task_id:
            raise TripoError(f"{path} did not return task_id", payload=body)
        _log(f"task created: {task_id} ({path.rsplit('/', 1)[-1]})")
        return str(task_id)

    # ------------------------------------------------------------------ #
    # 폴링
    # ------------------------------------------------------------------ #
    def get_task(self, task_id: str) -> TaskResult:
        body = self._request("GET", f"/tasks/{task_id}")
        return TaskResult.from_payload(body.get("data") or {})

    def wait(
        self,
        task_id: str,
        timeout: float = 600.0,
        interval: float = 2.0,
        max_interval: float = 15.0,
        on_progress: Callable[[TaskResult], None] | None = None,
    ) -> TaskResult:
        deadline = time.monotonic() + timeout
        delay = interval
        last_progress = -1
        while True:
            result = self.get_task(task_id)
            if result.progress != last_progress:
                last_progress = result.progress
                _log(f"{task_id}: {result.status} {result.progress}%")
                if on_progress:
                    on_progress(result)
            if result.status == TERMINAL_SUCCESS:
                return result
            if result.status in TERMINAL_FAILURES:
                raise TripoError(
                    f"task {task_id} ended as {result.status}"
                    f" (code={result.error_code}, message={result.error_message})",
                    code=result.error_code,
                    payload=result.raw or {},
                )
            if time.monotonic() > deadline:
                raise TripoError(
                    f"task {task_id} still {result.status} after {timeout:.0f}s; "
                    f"check it later with: get_task('{task_id}')"
                )
            time.sleep(delay)
            delay = min(delay * 1.6, max_interval)

    # ------------------------------------------------------------------ #
    # 다운로드
    # ------------------------------------------------------------------ #
    def download(self, url: str, dest: str | Path, chunk_size: int = 1 << 20) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with self.session.get(url, stream=True, timeout=self.timeout) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        handle.write(chunk)
        tmp.replace(dest)
        _log(f"downloaded {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
        return dest


# ---------------------------------------------------------------------- #
# payload 빌더 (순수 함수: 네트워크 없이 테스트 가능)
# ---------------------------------------------------------------------- #
def build_common_params(
    model: str = DEFAULT_MODEL,
    face_limit: int | None = None,
    geometry_quality: str | None = None,
    texture_quality: str | None = None,
    texture_version: str | None = None,
    pbr: bool = True,
    texture: bool = True,
    delight: bool | None = None,
    auto_size: bool = False,
    texture_alignment: str | None = None,
    model_seed: int | None = None,
    texture_seed: int | None = None,
    export_orientation: str | None = None,
) -> dict[str, Any]:
    """생성 API 공통 파라미터를 만든다. None인 값은 보내지 않는다."""
    params: dict[str, Any] = {"model": model}

    if pbr and not texture:
        raise ValueError("pbr=True requires texture=True (the API forces it anyway)")
    params["texture"] = bool(texture)
    if texture:
        params["pbr"] = bool(pbr)

    if face_limit is not None:
        if face_limit < 500:
            raise ValueError("face_limit must be at least 500")
        params["face_limit"] = int(face_limit)
    if geometry_quality:
        if geometry_quality not in ("standard", "detailed"):
            raise ValueError("geometry_quality is 'standard' or 'detailed' (detailed = Ultra mode)")
        if model.startswith("v2.") and geometry_quality == "detailed":
            raise ValueError("geometry_quality is only valid for model >= v3.0")
        params["geometry_quality"] = geometry_quality
    if texture_quality:
        if texture_quality not in ("fast", "standard", "detailed", "extreme"):
            raise ValueError("texture_quality is one of fast/standard/detailed/extreme")
        if texture_quality == "fast" and texture_version != TEXTURE_VERSION_V35:
            raise ValueError("texture_quality='fast' requires texture_version='v3.5-20260815'")
        params["texture_quality"] = texture_quality
    if texture_version:
        params["texture_version"] = texture_version
    if delight is not None:
        if delight and texture_version != TEXTURE_VERSION_V35:
            raise ValueError("delight is only read by texture_version='v3.5-20260815'")
        params["delight"] = bool(delight)
    if auto_size:
        params["auto_size"] = True
    if texture_alignment:
        if texture_alignment not in ("original_image", "geometry"):
            raise ValueError("texture_alignment is 'original_image' or 'geometry'")
        params["texture_alignment"] = texture_alignment
    if model_seed is not None:
        params["model_seed"] = int(model_seed)
    if texture_seed is not None:
        params["texture_seed"] = int(texture_seed)
    if export_orientation:
        params["export_orientation"] = export_orientation
    return params


def build_image_payload(image_input: str, **common: Any) -> dict[str, Any]:
    """image_input: 공개 URL, file_token, 또는 이전 이미지 생성 task_id."""
    if not image_input:
        raise ValueError("image input is empty")
    payload = {"input": image_input}
    payload.update(build_common_params(**common))
    return payload


def build_text_payload(prompt: str, negative_prompt: str | None = None, **common: Any) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is empty")
    if len(prompt) > 1024:
        raise ValueError("prompt is longer than 1024 characters")
    payload = {"prompt": prompt}
    if negative_prompt:
        if len(negative_prompt) > 255:
            raise ValueError("negative_prompt is longer than 255 characters")
        payload["negative_prompt"] = negative_prompt
    payload.update(build_common_params(**common))
    return payload


def build_convert_payload(
    task_or_token: str,
    format: str = "FBX",
    texture_size: int = 4096,
    texture_format: str = "PNG",
    fbx_preset: str = "blender",
    texture_packaging: str = "zip",
    face_limit: int | None = None,
    pack_uv: bool = False,
    pivot_to_center_bottom: bool = True,
) -> dict[str, Any]:
    """UE5 임포트용 변환 payload. FBX는 기본으로 텍스처를 zip으로 분리해 받는다."""
    fmt = format.upper()
    if fmt not in ("GLTF", "GLB", "FBX", "USDZ", "OBJ", "STL", "3MF"):
        raise ValueError(f"unsupported format: {format}")
    payload: dict[str, Any] = {
        "input": task_or_token,
        "format": fmt,
        "texture_size": int(texture_size),
        "texture_format": texture_format.upper(),
        "bake": True,          # 고급 머티리얼을 베이스 텍스처로 구워 엔진에서 단순하게 쓴다
        "pack_uv": bool(pack_uv),
        "pivot_to_center_bottom": bool(pivot_to_center_bottom),
    }
    if fmt == "FBX":
        payload["fbx_preset"] = fbx_preset
        payload["texture_packaging"] = texture_packaging  # "zip" -> .fbx + .fbm/ 폴더
    if face_limit is not None:
        payload["face_limit"] = int(face_limit)
    return payload


def dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
