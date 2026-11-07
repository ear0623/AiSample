# TRELLIS.2 로컬 GPU 파이프라인 구축

TRELLIS.2는 Microsoft Research가 공개한 이미지→3D 모델입니다(4B 파라미터, MIT).
SDF 대신 **O-Voxel**이라는 희소 복셀 표현을 써서, 열린 표면(옷·잎), 비매니폴드, 내부 폐쇄 구조를 손실 없이 다루고 **PBR 파라미터(Base Color / Roughness / Metallic / Opacity)를 함께 생성**합니다.

> 이 문서는 2026-11 기준 공식 저장소 README를 근거로 정리했습니다. 설치는 저장소가 갱신되면 달라질 수 있으니 `setup.sh --help`와 README를 먼저 확인하세요.

## 1. 요구사항

| 항목 | 요구 |
| --- | --- |
| OS | **Linux** (공식 테스트 기준. Windows는 WSL2 + CUDA 또는 API 경로 권장) |
| GPU | **NVIDIA 24GB VRAM 이상** (A100/H100에서 검증) |
| CUDA | 12.4 권장 (CUDA Toolkit 필요 — 일부 패키지 컴파일) |
| Python | 3.8+ (conda 권장) |
| 디스크 | 가중치·의존성 포함 수십 GB |

속도(H100 기준): 512³ 약 3초 · 1024³ 약 17초 · 1536³ 약 60초. VRAM이 빠듯하면 512³로 시작해 올리세요.

## 2. 설치

```bash
git clone -b main https://github.com/microsoft/TRELLIS.2.git --recursive
cd TRELLIS.2

# CUDA Toolkit 12.4를 쓴다면 명시 (여러 버전이 깔린 경우 필수)
export CUDA_HOME=/usr/local/cuda-12.4

# conda 환경 새로 만들며 기본 의존성 + 확장 패키지 설치
. ./setup.sh --new-env --basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel --flexgemm
```

- `--new-env`를 빼면 현재 conda 환경에 설치합니다.
- flash-attn을 지원하지 않는 GPU(V100 등)라면 `xformers`를 설치하고 `ATTN_BACKEND=xformers`를 설정합니다.
- 설치가 한 번에 안 되면 README 안내대로 플래그를 하나씩 나눠 설치하세요.

가중치 `TRELLIS.2-4B`는 Hugging Face에서 자동으로 받습니다: https://huggingface.co/microsoft/TRELLIS.2-4B

## 3. 최소 실행 예제

공식 README의 예제를 이 파이프라인 기준으로 정리한 것입니다.

```python
import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"  # VRAM 절약

import cv2, imageio, torch
from PIL import Image
from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.utils import render_utils
from trellis2.renderers import EnvMap
import o_voxel

# 1) 환경맵 (PBR 미리보기 렌더용)
envmap = EnvMap(torch.tensor(
    cv2.cvtColor(cv2.imread("assets/hdri/forest.exr", cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB),
    dtype=torch.float32, device="cuda"))

# 2) 파이프라인 로드
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
pipeline.cuda()

# 3) 생성
image = Image.open("input/chair.png")
mesh = pipeline.run(image)[0]
mesh.simplify(16777216)  # nvdiffrast 메모리 한계

# 4) (선택) 미리보기 렌더
video = render_utils.make_pbr_vis_frames(render_utils.render_video(mesh, envmap=envmap))
imageio.mimsave("chair.mp4", video, fps=15)

# 5) GLB로 내보내기 — 여기서 decimation이 사실상 폴리곤 예산이다
glb = o_voxel.postprocess.to_glb(
    vertices=mesh.vertices,
    faces=mesh.faces,
    attr_volume=mesh.attrs,
    coords=mesh.coords,
    attr_layout=mesh.layout,
    voxel_size=mesh.voxel_size,
    aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
    decimation_target=1000000,   # 100만 폴리곤. 게임용은 100k~300k부터
    remesh=True, remesh_band=1, remesh_project=0, verbose=True,
)
glb.export("chair.glb", extension_webp=False)
```

**중요:** `extension_webp=True`(기본값)로 내보내면 GLB 안의 텍스처가 WebP로 들어갑니다. UE5의 glTF 임포터는 WebP 임베드를 처리하지 못하는 버전이 있으니, 엔진으로 넘길 때는 `False`로 두고 PNG/JPEG로 받으세요.

## 4. 이 저장소의 파이프라인에 연결

TRELLIS.2의 출력도 "PBR 맵이 GLB에 심어진" 형태라서, 추출·패킹 단계는 API 경로와 동일합니다.

```bash
# 1) GLB 구성 확인 (머티리얼/텍스처/삼각형 수)
python pipeline/glb_texture_tools.py info chair.glb

# 2) PBR 맵 분리 (basecolor / metallic_roughness / normal, MR은 roughness·metallic으로도 분해)
python pipeline/glb_texture_tools.py extract chair.glb -o output/chair/textures --prefix T_Chair_

# 3) UE5 ORM 패킹
python pipeline/texture_packer.py \
  --metallic-roughness output/chair/textures/T_Chair_metallic_roughness.png \
  -o output/chair/textures/T_Chair_ORM.png
```

TRELLIS.2는 보통 AO 맵을 함께 내지 않습니다. ORM의 R은 255로 채워지며, 필요하면 노멀맵 기반 AO나 DCC 베이킹으로 채우세요.

## 5. 배치로 돌릴 때

한 프로세스에서 파이프라인을 한 번만 로드하고 이미지를 순회하는 편이 훨씬 빠릅니다(모델 로드가 수십 초).

```python
from pathlib import Path
from PIL import Image

pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
pipeline.cuda()

for path in sorted(Path("input").glob("*.png")):
    mesh = pipeline.run(Image.open(path))[0]
    mesh.simplify(16777216)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
        coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=300000, remesh=True, remesh_band=1, remesh_project=0,
    )
    out = Path("output") / path.stem
    out.mkdir(parents=True, exist_ok=True)
    glb.export(str(out / "model.glb"), extension_webp=False)
    print("done", out)
```

VRAM이 부족하면: 해상도를 512³로 낮추고, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`를 유지하고, 배치 크기를 1로 두세요.

## 6. 트러블슈팅

| 증상 | 원인/해결 |
| --- | --- |
| `flash-attn` 빌드 실패 | CUDA Toolkit 버전 확인(`CUDA_HOME`), 또는 `xformers` + `ATTN_BACKEND=xformers` |
| CUDA out of memory | 512³로 낮추기, `expandable_segments:True`, 프로세스 재시작 |
| `--new-env` 없이 설치했는데 import 실패 | conda 환경 활성화 여부, PyTorch CUDA 버전 일치 확인 |
| GLB 텍스처가 엔진에서 안 보임 | `extension_webp=False`로 재출력 |
| 결과가 뿌옇다 | 복셀 해상도 상향(1024³/1536³), decimation_target 상향 |
| 투명한 부분이 사라짐 | GLB export 기본이 OPAQUE — 알파가 필요하면 머티리얼 블렌드 설정 확인 |

## 7. Windows에서 쓸 때

공식 지원은 Linux입니다. Windows에서 시도한다면:

1. **WSL2 + CUDA** — 가장 현실적. WSL에서 GPU 패스스루가 되면 위 절차를 그대로 따릅니다.
2. **Docker** — 저장소가 제공하는 이미지를 쓰는 방법.
3. **API 경로** — 로컬 구축 비용이 부담되면 `pipeline/tripo_pbr_generator.py`로 클라우드에서 동일한 산출물(PBR GLB)을 얻고, 후처리는 이 저장소 스크립트로 처리하세요.
