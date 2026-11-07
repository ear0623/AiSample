# 고품질 AI 3D 에셋 파이프라인

이미지 한 장 또는 텍스트 프롬프트에서 **게임 엔진에 바로 넣을 수 있는 고밀도 메시 + PBR 텍스처**를 뽑아내는 파이프라인입니다.
AI 생성 결과물을 "예쁜 스크린샷"에서 "엔진에서 조명을 받아도 버티는 에셋"으로 바꾸는 데 필요한 것들 —
텍스처 분리, de-lighting, ORM 패킹, 블렌더 리토폴로지·베이킹, Nanite 임포트 — 을 코드와 문서로 정리했습니다.

- 생성 엔진: **Tripo3D API v3.1** (클라우드, 최대 200만 삼각형 Ultra 모드) · **Microsoft TRELLIS.2** (로컬 GPU, MIT)
- 타깃 엔진: **Unreal Engine 5** (Nanite + Lumen), glTF/FBX 공통 규격 준수
- 가공/베이킹: **Blender 3.6 LTS / 4.x / 5.x** (리토폴로지, UV, Cycles 하이폴리→로우폴리 베이킹)
- 언어: Python 3.9+

```
이미지 / 프롬프트
      │
      ▼
[생성 API] ── Tripo3D v3.1 (texture_quality, geometry_quality=detailed)
      │        또는 TRELLIS.2 로컬 파이프라인
      ▼
   model.glb  ── PBR 맵이 이미지로 심어져 있음
      │
      ├─▶ glb_texture_tools.py   basecolor / metallic_roughness / normal / occlusion 분리
      │
      ├─▶ texture_packer.py      R=AO, G=Roughness, B=Metallic 으로 ORM 패킹
      │
      ├─▶ (선택) FBX + 분리 텍스처 zip 변환   ── UE5 임포트용
      │
      ├─▶ blender_import.py      블렌더: PBR 노드 구성 → (경로 B) 감면·UV·케이지·베이킹 → FBX/GLB
      │
      ▼
  manifest.json  ── task id, 크레딧, 파일 목록, 경고 기록
      │
      ▼
  UE5: Interchange 임포트 → 텍스처 압축 설정 → 머티리얼 인스턴스 → Nanite
      (경로 A: Nanite 정적 프랍은 원본 유지 / 경로 B: 캐릭터·모바일은 로우폴리 + 베이킹)
```

## 무엇이 들어 있나

| 경로 | 설명 |
| --- | --- |
| `pipeline/tripo_pbr_generator.py` | Tripo3D API로 이미지/텍스트 → 3D 생성 → GLB 다운로드 → 텍스처 추출 → ORM → (선택) FBX 변환까지 한 번에. 배치/재개 지원 |
| `pipeline/tripo_client.py` | API 클라이언트 (재시도, 폴링, 에러 코드 해석). payload 빌더는 순수 함수라 테스트 가능 |
| `pipeline/glb_texture_tools.py` | GLB 바이너리를 직접 파싱해 PBR 맵을 슬롯별로 추출. `info`로 메시/머티리얼 요약 |
| `pipeline/texture_packer.py` | AO/Roughness/Metallic(또는 glTF MR) → UE5 표준 ORM 텍스처. 채널 통계 검증 포함 |
| `pipeline/ue5_import.py` | UE5 에디터 파이썬용 임포트 도우미 (임포트 → 텍스처 설정 → MI 생성 → Nanite) |
| `pipeline/blender_import.py` | 블렌더용. 임포트·검사 → PBR 머티리얼 노드 → (경로 B) 목표 삼각형 감면·UV·케이지 → Cycles 베이킹 → FBX/GLB 익스포트 |
| `docs/pbr_material_pipeline.md` | **핵심 문서.** 텍스처 디커플링 원리, PBR 맵 설계, 채널 패킹, UE5 머티리얼 구성, 검증 체크리스트 |
| `docs/blender_pipeline.md` | **블렌더 가공 문서.** 폴리곤 감면 의사결정, Decimate/Quadriflow, UV·케이지, Cycles 하이폴리→로우폴리 베이킹, 색공간, 엔진 익스포트 |
| `docs/trellis2_local_setup.md` | TRELLIS.2 로컬 GPU 파이프라인 구축 가이드 (24GB VRAM, Linux) |
| `tests/test_pipeline.py` | 41개 테스트 — GLB 파싱, 채널 매핑, ORM 패킹, payload 검증, API 재시도/에러, 블렌더 텍스처 슬롯·감면 계산 |

## 빠른 시작

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export TRIPO_API_KEY=tsk_...                          # https://platform.tripo3d.ai 에서 발급
```

### 1) 레퍼런스 이미지 → 고품질 PBR 에셋

```bash
python pipeline/tripo_pbr_generator.py image refs/chair.png \
  --name chair \
  --geometry-quality detailed \
  --face-limit 2000000 \
  --texture-quality detailed \
  --texture-version v3.5-20260815 \
  --ue5
```

### 2) 텍스트 프롬프트 → 에셋

```bash
python pipeline/tripo_pbr_generator.py text \
  "a medieval wooden treasure chest with iron hinges, weathered paint" \
  --name chest --face-limit 120000
```

### 3) 여러 개를 한 번에

`assets/example_batch.json` 형식으로 목록을 만들고:

```bash
python pipeline/tripo_pbr_generator.py batch assets/example_batch.json
```

### 4) API 호출 없이 옵션만 확인

```bash
python pipeline/tripo_pbr_generator.py image refs/chair.png --name chair --dry-run
```

### 산출물 구조

```
output/chair/
├── model.glb                       # 생성 원본 (PBR 맵 임베드)
├── preview.png                     # 렌더 미리보기
├── manifest.json                   # task id, 크레딧, 파라미터, 파일 목록, 경고
├── textures/
│   ├── T_Chair_basecolor.png
│   ├── T_Chair_normal.png
│   ├── T_Chair_metallic_roughness.png   # glTF 원본 (G=rough, B=metal)
│   ├── T_Chair_roughness.png            # 채널 분해
│   ├── T_Chair_metallic.png
│   ├── T_Chair_occlusion.png            # GLB에 AO가 있을 때만
│   └── T_Chair_ORM.png                  # UE5용 최종 (R=AO, G=Rough, B=Metal)
└── ue5/                            # --ue5 옵션 시
    ├── chair.fbx
    └── chair.fbm/                  # 분리된 텍스처들

output/hero/                        # 블렌더 경로 B 실행 후
├── hero.blend                      # 하이폴리/로우폴리/케이지, 텍스처 pack
├── hero_low.fbx                    # 엔진용 로우폴리
├── blender_report.json             # 검사·감면·베이킹·경고 기록
└── baked/
    ├── T_hero_Low_basecolor.png
    ├── T_hero_Low_normal.png
    ├── T_hero_Low_roughness.png
    └── T_hero_Low_ao.png
```

### 5) 블렌더에서 가공·베이킹 (경로 B: 캐릭터/모바일)

```bash
blender --background --factory-startup --python pipeline/blender_import.py -- \
  --model output/hero/model.glb \
  --target-tris 30000 \
  --bake normal,ao,roughness,basecolor \
  --bake-size 2048 \
  --export-fbx output/hero/hero_low.fbx \
  --blend output/hero/hero.blend
```

하이폴리 원본을 `hero_High`로 보존하고 `hero_Low`를 목표 삼각형 수까지 감면한 뒤, UV·케이지를 만들고 Cycles로 노멀/AO/러프니스/베이스컬러를 베이킹해 로우폴리 머티리얼까지 구성합니다.
UE5 Nanite 정적 프랍(경로 A)은 감면 없이 임포트만 합니다.

```bash
blender --background --factory-startup --python pipeline/blender_import.py -- \
  --model output/chair/model.glb --scale-target 1.0 --origin bottom \
  --blend output/chair/chair.blend
```

## 핵심 옵션

| 옵션 | 의미 | 권장 |
| --- | --- | --- |
| `--geometry-quality detailed` | Ultra 모드. 더 촘촘한 지오메트리 | 히어로 에셋. 배경 소품은 `standard` |
| `--face-limit` | 최대 삼각형 수 | v3.1 Ultra 상한 2,000,000 / 게임 최적화 50k~100k / 웹·모바일 10k~50k |
| `--texture-quality` | `standard` / `detailed` / `extreme`(8K) / `fast` | `detailed` 기본, 클로즈업 히어로만 `extreme`(크레딧 추가) |
| `--texture-version v3.5-20260815` | v3.5 텍스처 모델. `delight`와 `fast`가 여기서만 동작 | 실사풍 프로젝트라면 켜고 `--delight` 유지 |
| `--delight` | 레퍼런스 이미지에 구워진 조명을 제거 | 기본 켜짐(v3.5). 스타일라이즈드 아트면 `--no-delight` |
| `--auto-size` | 실제 스케일(미터)로 정규화 | 엔진에서 스케일 맞출 때 유용 |
| `--ue5` | FBX + 분리 텍스처 zip으로 변환 | UE5로 바로 임포트할 때 |
| `--force` | 이미 성공한 에셋도 재생성 | 프롬프트/옵션을 바꿨을 때 |

`manifest.json`의 `credits_consumed`에 실제 소비 크레딧이 기록되므로, 배치를 돌린 뒤 비용을 파일 단위로 집계할 수 있습니다.

## 모듈로 쓰기

```python
from pipeline.glb_texture_tools import extract_textures
from pipeline.texture_packer import pack_orm, verify

maps = extract_textures("output/chair/model.glb", "output/chair/textures", prefix="T_Chair_")
pack_orm(
    occlusion=maps.get("occlusion"),
    metallic_roughness=maps["metallic_roughness"],
    out_path="output/chair/textures/T_Chair_ORM.png",
)
print(verify("output/chair/textures/T_Chair_ORM.png"))
```

## 문서

- **[docs/pbr_material_pipeline.md](docs/pbr_material_pipeline.md)** — 머티리얼 텍스처를 이용한 고품질 3D 에셋 제작 및 UE5 연동 가이드
  1. 텍스처 디커플링 원리와 de-lighting
  2. PBR 맵 구성과 역할
  3. 최신 AI 생성 파이프라인 (Tripo3D v3.1 / TRELLIS.2)
  4. 채널 패킹 (ORM)
  5. UE5 임포트·머티리얼·Nanite·Lumen
  6. 품질 검증 체크리스트
- **[docs/blender_pipeline.md](docs/blender_pipeline.md)** — 블렌더에서의 AI 3D 에셋 가공
  1. 폴리곤 감면 의사결정(경로 A: Nanite 직결 / 경로 B: 캐릭터·모바일)
  2. 임포트 주의점과 고밀도 원본 검사
  3. Decimate·Quadriflow·Voxel Remesh와 캐릭터 리토폴로지
  4. UV 언랩과 베이킹 케이지
  5. Cycles 하이폴리→로우폴리 베이킹 (normal/AO/roughness/basecolor/metallic)
  6. Principled 노드 구성과 색공간, 엔진 익스포트 설정
- **[docs/trellis2_local_setup.md](docs/trellis2_local_setup.md)** — 로컬 GPU에서 TRELLIS.2 돌리기

## 테스트

```bash
python -m unittest discover -s tests -v
```

API 키 없이 돌아갑니다. 가짜 GLB를 만들어 GLB 파싱·채널 매핑·ORM 패킹·payload 검증·재시도 로직을 확인합니다.

## 사용 전에 알아둘 것

- **생성 서비스 약관과 학습 데이터**: 상용 프로젝트에 쓰기 전에 각 서비스의 라이선스(출력물 소유권, 상업적 이용)를 확인하세요. TRELLIS.2는 MIT지만 의존 패키지(nvdiffrast, nvdiffrec 등)는 별도 라이선스입니다.
- **AI 텍스처의 한계**: 근접 클로즈업에서는 텍스처에 조명 정보가 남거나 UV seam이 보일 수 있습니다. 히어로 에셋은 생성 → 리토폴로지 → 재베이킹(Substance 등) 순서를 권장합니다. 자세한 판단 기준은 문서 1.4절.
- **경로 판단**: UE5 Nanite 정적 프랍은 폴리곤을 줄일 필요가 없습니다(원본 유지). 캐릭터/스키닝, 모바일, 비-Nanite 타깃은 블렌더에서 감면·UV·베이킹이 필수입니다. 판단 기준과 절차는 [docs/blender_pipeline.md](docs/blender_pipeline.md) 0장·3~5장.
- **비용**: Tripo3D는 크레딧 과금입니다. `face_limit`·`texture_quality`가 올라가면 소비량도 올라가므로, 배경 소품은 낮은 설정으로 먼저 테스트하세요.
- **버전**: API 파라미터와 모델명은 2026-11 기준 공식 문서를 따랐습니다. 서비스가 갱신되면 `pipeline/tripo_client.py`의 상수(`DEFAULT_MODEL`, `TEXTURE_VERSION_V35`)와 문서 3.2절을 함께 갱신하세요.
