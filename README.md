# 고품질 AI 3D 에셋 파이프라인

이미지 한 장 또는 텍스트 프롬프트에서 **게임 엔진에 바로 넣을 수 있는 고밀도 메시 + PBR 텍스처**를 뽑아내는 파이프라인입니다.
AI 생성 결과물을 "예쁜 스크린샷"에서 "엔진에서 조명을 받아도 버티는 에셋"으로 바꾸는 데 필요한 것들 —
텍스처 분리, de-lighting, ORM 패킹, 블렌더 리토폴로지·베이킹, Nanite 임포트 — 을 코드와 문서로 정리했습니다.
여기에 더해, 이 저장소는 **오픈월드 월드 제작 가이드**(지형·월드 파티션·PCG·라이팅·최적화)와
착수 전 수치 설계를 위한 **계획 계산기·체크리스트**를 제공합니다.
같은 라인에서 **오픈월드 콘텐츠·건축 설계 매뉴얼**(탈것·아이템·건물·배경 배치, 인게임 건축, 건축학 용어·도면·게임 스케일)과
**언리얼 캐릭터 제작·커스터마이징 가이드**(PC/NPC, 모듈러 의상, 외모 커스터마이징)를 C++ 예제와 함께 제공합니다.
여기에 **인게임 실내 탐사 수치·공간 묘사 가이드**(복도·문·층고·계단 실측 수치, 3인칭 카메라 붐 계산, 환경 스토리텔링, 방 단위 최적화)를
복도 폭·문 폭·층고·암 길이를 넣으면 클리핑 위험도와 쾌적도를 계산하는 CLI와 함께 넣었습니다.
그리고 **절차 생성 차량·실내 에셋 트러블슈팅 가이드**(LP 저작·베이킹 무결점·텍스처 VRAM 예산)를
차종 수·해상도·포맷으로 18 차종 VRAM 을 계산하고, 익스플로전 오프셋·케이지 여유를 검사하는 도구와 함께 넣었습니다.

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
| `pipeline/mcp_token_optimizer.py` | MCP 도구 정의·결과 페이로드 토큰 최적화 (BM25/임베딩 라우터, 스키마 프루닝, Summary-First). 3D 파이프라인과 무관한 독립 모듈, 표준 라이브러리만 사용 |
| `docs/mcp_token_optimization_guide.md` | **MCP 토큰 절약 가이드.** 도구 정의 오버헤드 분석, 동적 로딩·툴 검색, 프롬프트 캐싱, 스키마 경량화, 페이로드 압축, 컴팩션, 게이트웨이, 클라이언트 설정 |
| `tests/test_mcp_optimizer.py` | 51개 테스트 — 토큰 근사, 라우팅 정확도·결정성, 스키마 프루닝, 표 변환·페이징·트렁케이션 |
| `pipeline/open_world_helper.py` | 오픈월드 계획 계산기 — 월드 파티션 그리드·스트리밍 처리량, 랜드스케이프 크기·높이 정밀도, RVT 해상도·메모리, HLOD 프록시 수, 38항목 체크리스트 검증. 표준 라이브러리만 사용 |
| `docs/open_world_creation_pipeline.md` | **오픈월드 제작 가이드.** LWC 좌표계, 지형 DCC/임포트, RVT, World Partition·Data Layer·OFPA, PCG·Nanite Foliage, 도로·수계, Lumen·VSM·대기, HLOD·프로파일링, 8단계 로드맵 |
| `tests/test_open_world_helper.py` | 66개 테스트 — 셀 반경 계산, 스트리밍 윈도우, 랜드스케이프 크기·정밀도, RVT 해상도·메모리, HLOD, 체크리스트 점수·블로커 |
| `docs/open_world_content_and_architecture_guide.md` | **콘텐츠·건축 설계 매뉴얼.** 탈것(Chaos Vehicles·네트워크·승하차·주행 AI), 아이템(PrimaryDataAsset·GAS·드롭·스트리밍), 건축 모듈러 킷·루멘 누광, 배경 드레싱·POI, **인게임 건축(프리뷰·스냅·지지 그래프·서버 권위)**, **디테일 기법(트림 시트·가중치 노멀·DBuffer 데칼·버텍스 컬러·패럴랙스)**, 건축학 용어·도면·인간공학 vs 게임 스케일·모듈러 설계 |
| `docs/unreal_character_and_customization_guide.md` | **캐릭터 가이드.** PC/NPC 클래스 계층·컨트롤러 분기, Significance Manager·Animation Budget Allocator, 모듈러 의상(Leader Pose·병합 비교·클로스·클리핑), 외모 커스터마이징(모프·본 스케일·MID·Groom·직렬화·복제) |
| `examples/unreal_cpp_character/` | `CharacterCustomizationTypes.h`(슬롯·정의·NetSerialize), `ModularCharacter.h/.cpp`(리더 포즈·비동기 장착·모프·MID·바디 마스킹·서버 RPC) |
| `examples/unreal_cpp_building/` | `BuildingTypes.h`, `BuildSystemComponent.h/.cpp`(고스트 프리뷰·소켓/그리드 스냅·검증·RPC), `BuildManager.h/.cpp`(서버 검증·스폰·지지 그래프 BFS·연쇄 붕괴) |
| `tests/test_cpp_examples.py` | 15개 테스트 — 헤더 규약, 괄호 균형, 선언↔정의, `ReplicatedUsing`↔`OnRep`, NetSerialize, 문서 링크·필수 섹션 |
| `pipeline/indoor_metric_helper.py` | 실내 탐사 수치 계산기 — 용도별 프리셋(주거·오피스·상업·던전·산업), 복도 폭·문·층고·암 길이로 카메라 클리핑 위험도·쾌적도 판정, 계단 Blondel·법규·CMC 정합, 소품 밀도 예산. 표준 라이브러리만 사용 |
| `docs/indoor_exploration_and_spatial_metrics.md` | **실내 탐사 가이드.** 플레이어·복도·문·층고·계단·가구 치수, SpringArm 기하와 동적 단축·벽 페이드(C++), 4층위 환경 스토리텔링·단서 설계·조명·발소리, 방 배치 토폴로지·소품 예산·방 단위 수면·프로파일링 |
| `tests/test_indoor_metrics.py` | 63개 테스트 — 카메라 기하(자유 요·허용 암·피치), 공간 판정·블로커, 계단 비·법규·CMC, 프리셋 정합, 소품 밀도, CLI JSON/에러 |
| `pipeline/vehicle_asset_optimizer.py` | 차량 텍스처 VRAM 계산기 + 베이킹 도구 — 포맷별 bpp·밉 체인 실크기, 차종/대수별 상주량·예산 비율·절감 시나리오, ORM 패킹 절감률, 겹판 익스플로전 오프셋, 케이지 여유(0.4~35%) 검증, 12단계 체크리스트. 표준 라이브러리만 사용 |
| `docs/blender_asset_production_troubleshooting_guide.md` | **차량 에셋 트러블슈팅 가이드.** Geometry Nodes `IsLowPoly` 스위치와 프로파일 세그먼트 오차 계산, 차체 리토폴로지 3방법 비교(VDB+Decimate+Shrinkwrap), 커스텀 노멀 전송 순서, 클러스터 6+1 분할, 겹판·광선 놓침·탄젠트(MikkTSpace·3c), 18 차종 1,440 MiB VRAM 계산과 2,000대 인스턴싱 |
| `tests/test_vehicle_asset_optimizer.py` | 109개 테스트 — 포맷 크기·밉 체인·블록 최소 1블록, 함대 예산·판정·시나리오, ORM 절감률(66.7%/33.3%), 익스플로전 그룹·잔여 겹침, 케이지 토폴로지·여유·실루엣, CLI 텍스트/JSON, 문서 정합 |

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
- **[docs/mcp_token_optimization_guide.md](docs/mcp_token_optimization_guide.md)** — MCP 연동 시 토큰 절약
  1. 토큰 폭증 원인(도구 정의·원시 페이로드·히스토리 누적)과 비용 계산
  2. 동적 도구 로딩(툴 검색·점진적 공개·코드 실행/Code Mode)
  3. 프롬프트 캐싱과 MCP 서버를 캐시 친화적으로 만드는 규칙
  4. JSON Schema 경량화
  5. 결과 페이로드 압축(Summary-First·표 변환·페이징)
  6. 컨텍스트 편집·히스토리 컴팩션
  7. 게이트웨이/프록시 아키텍처와 오픈소스 도구
  8. 클라이언트별 설정과 벤치마크
- **[docs/open_world_creation_pipeline.md](docs/open_world_creation_pipeline.md)** — 오픈월드 제작 파이프라인 (UE 5.8 기준)
  1. 코어 아키텍처: Large World Coordinates, 셀·로딩 반경·스트리밍 처리량
  2. 지형: Houdini/World Machine/Gaea 침식, 16-bit 하이트맵, Landscape 구조, RVT, 변위
  3. 월드 파티션: 런타임 그리드, Streaming Source, Data Layer, OFPA, HLOD
  4. PCG와 식생: 바이옴, PCG 그래프, HISM/Nanite Foliage
  5. 인프라: 스플라인 도로, Water Body·Gerstner·부력
  6. 대기·라이팅: Sky Atmosphere, Volumetric Cloud, Lumen, VSM, 시간대
  7. 최적화: HLOD, 컬링, 텍스처/VT 풀, 프로파일링 도구
  8. 8단계 제작 로드맵과 게이트 조건
  9. 계산기·체크리스트 사용법
- **[docs/open_world_content_and_architecture_guide.md](docs/open_world_content_and_architecture_guide.md)** — 오픈월드 콘텐츠 제작·배치와 건축 설계
  1. 탈것: Chaos Vehicles 물리 셋업·서스펜션 계산·네트워크 모드·승하차·스플라인 주행
  2. 아이템: PrimaryDataAsset 데이터베이스·상호작용 인터페이스·GAS·월드 드롭 인스턴싱·상태 저장
  3. 건축물: 모듈러 킷·벽 두께와 루멘 누광·실내 컬링(오클루전 포탈의 대안)
  3.8 **인게임 건축 시스템**: 고스트 프리뷰, 소켓/그리드 스냅, 지지 그래프와 연쇄 붕괴, 서버 권위 흐름
  3.9 **디테일 표현**: 트림 시트+가중치 노멀, DBuffer 데칼+RVT, 버텍스 컬러 다층 블렌드, 윈도우 인테리어 패럴랙스, 빛샘 방지 수치
  4. 배경: POI·랜드마크 길찾기, 레벨 드레싱 규칙, HISM·클러터
  5. 건축학 용어: 구조·입면·장식·한국 전통 건축·오더와 양식
  6. 도면: 평면/입면/단면/상세, 도면 규약, 도면→게임 워크플로우
  7. 인간공학 vs 게임 스케일: 문·복도·계단·난간 수치와 CMC 정합
  8. 모듈러 설계: 100/200/400/500 그리드, 평면·입면·구조 경간, 킷 검증
- **[docs/unreal_character_and_customization_guide.md](docs/unreal_character_and_customization_guide.md)** — 캐릭터 제작·커스터마이징 (C++)
  1. PC vs NPC: 클래스 계층, Enhanced Input, AIController·StateTree·EQS, 제작 파이프라인 차이
  2. 대량 캐릭터: Significance Manager, Animation Budget Allocator, URO, LOD별 감축
  3. 모듈러 의상: 리더 포즈의 원리와 함정, 분리 vs 런타임 병합, 클로스, 클리핑 4단계 방어
  4. 외모 커스터마이징: 모프 타깃, 본 스케일링, MID·피부·Groom, 직렬화·복제·저장
  5. 예제 코드: `examples/unreal_cpp_character`, `tests/test_cpp_examples.py` 검증 항목
- **[docs/indoor_exploration_and_spatial_metrics.md](docs/indoor_exploration_and_spatial_metrics.md)** — 인게임 실내 탐사 수치와 공간 세부 묘사
  1. 플레이어·복도·문·천장·계단·가구의 실측 수치와 UE 기본값의 차이
  2. 3인칭 카메라 붐 기하: 자유 회전각·필요 복도 폭·동적 단축·벽 페이드(C++)
  3. 시간의 4층위, 3단서+1질문, 밀도·리듬, 길찾기·프레이밍, 조명·발소리
  4. 방 배치 토폴로지·락앤키, 소품 밀도 예산, 방 단위 오클루전·수면, 예산표
- **[docs/blender_asset_production_troubleshooting_guide.md](docs/blender_asset_production_troubleshooting_guide.md)** — 절차 생성 차량·실내 에셋 트러블슈팅
  1. LP 저작: `IsLowPoly` 스위치, 프로파일 세그먼트 감축(sagitta 공식), 베벨 단계, 매니페스트
  2. 복잡 곡면: Edge-Angle Decimate / QuadriFlow / VDB Remesh+Shrinkwrap 선택 기준, 3면 실루엣 오차
  3. Shrinkwrap 가중치, Data Transfer 커스텀 노멀(4.1+ auto smooth 제거), 클러스터 6+1, LP 검증 게이트
  4. 베이킹: 겹판(BVH 진단·익스플로전·복원), 광선 놓침(케이지 표준·Max Ray Distance 비교), 탄젠트와 3c
  5. VRAM: MiB/밉/블록 규칙, 18 차종 1,440 MiB, ORM 패킹 66.7%, 2,000대 0.49 MiB, VT·스트리밍 풀, 실내 1024 타일
  6. 12단계 체크리스트, 트러블슈팅 매트릭스, 엔진 임포트 세팅

## 오픈월드 월드 제작

오픈월드는 기능의 합이 아니라 예산의 합입니다. 셀 크기·로딩 반경·RVT 해상도·HLOD 셀처럼
나중에 바꾸면 월드 전체를 다시 만들어야 하는 숫자를 착수 전에 확정하는 계산기와,
빠뜨리기 쉬운 항목을 모은 체크리스트가 함께 있습니다(표준 라이브러리만 사용).

```bash
python pipeline/open_world_helper.py grid --world-km 8 --cell-m 256 --loading-range-m 768 \
    --bytes-per-cell 30000000 --speed-mps 6
```

```text
월드 8,000 m  |  셀 256 m  |  로딩 반경 768 m
  그리드            32 x 32 = 1,024 셀
  동시 로드 셀      최대 45개 (7x7 정사각형의 모서리 제외)
  셀 통과 시간      42.7 s  (분당 1.4 셀, 6 m/s)
  로드 윈도우       106.7 s
  셀 데이터         28.6 MB  -> 필요 처리량 0.3 MB/s
  상주 추정         1,287 MB
```

```bash
python pipeline/open_world_helper.py landscape --target-m 4000 --spacing-m 1.0
python pipeline/open_world_helper.py rvt --world-m 8129 --texels-per-m 0.5 --layout base_color_normal
python pipeline/open_world_helper.py hlod --world-km 8
python pipeline/open_world_helper.py checklist --print-default > world_status.json
```

| 명령 | 계산하는 것 |
| --- | --- |
| `grid` | 셀 수, 동시 로드 셀, 로딩 윈도우, 필요 스트리밍 처리량, 상주 메모리 |
| `landscape` | 권장 정점 크기, 컴포넌트·드로우콜, Z scale, 높이 정밀도, 하이트맵 용량 |
| `rvt` | 해상도·타일 수, 텍셀당 바이트, mip0/전체 밉/페이지 테이블/풀 메모리 |
| `hlod` | 레이어별 프록시 액터 수, 동시 로드 수, 빌드 시간 추정, 배치 경고 |
| `checklist` | 38개 항목의 준비도 점수와 필수 블로커 |

배경 이론과 실무 판단 기준은 [docs/open_world_creation_pipeline.md](docs/open_world_creation_pipeline.md)에 정리했습니다
(2026-11, UE 5.8 기준. Mesh Terrain/Nanite Foliage/Water/Fast Geometry Streaming은 실험 표기).

## 실내 탐사 수치

실내는 "지나갈 수 있는가"와 "카메라가 벽을 뚫는가"가 별개 문제입니다. 복도 180 cm, 문 120 cm를 맞춰도
3인칭 카메라가 벽에 붙으면 그 방은 못 쓰게 됩니다. 아래 계산기는 복도·문·층고·암 길이를 받아
자유 회전각과 필요 후퇴량을 풀어 클리핑 위험도와 쾌적도를 내고, 계단과 소품 밀도까지 같이 검사합니다.

```bash
python pipeline/indoor_metric_helper.py presets          # 용도별 프리셋
python pipeline/indoor_metric_helper.py check --preset office_lab --corridor 200
python pipeline/indoor_metric_helper.py camera --corridor 180 --ceiling 300 --arm 220 --pitch 15
python pipeline/indoor_metric_helper.py stairs --riser 18 --tread 28 --floor-height 320
python pipeline/indoor_metric_helper.py clutter --area 40 --grade dense
```

```text
주의  |  쾌적도 79.4 / 100  |  클리핑 위험도 63.3 / 100  (residential)
  (위험도는 카메라를 벽 쪽으로 완전히 돌렸을 때 기준 — 낮을수록 여유가 크다)
  복도 180 cm | 문 110x220 cm | 천장 300 cm | 암 220 cm
  카메라: 좌우 +-21.5도, 상향 38.2도, 허용 암 81 cm (first_person)

  [OK  ] 복도 1인 통과                         180 cm  폭 180 cm, 캡슐 지름 68 cm(어깨 46 cm보다 22 cm 큼) -> 좌우 여유 56 cm. 탐사 기준 150 cm 미만이면 벽이 시야를 계속 때린다
  [WARN] 2인 교행                            180 cm  두 캐릭터(60 cm) + 사이 여유 60 cm = 180 cm 필요. NPC가 지나다니는 공간이면 200 cm 이상
  [FAIL] 카메라 좌우 회전 여유                  21.53 deg  암 220 cm로 좌우 22도까지 벽에 닿지 않는다 (필요 각 45도)
  ...
```

| 명령 | 계산하는 것 |
| --- | --- |
| `presets` / `preset` | 주거·오피스·상업·던전·산업의 권장 복도·문·천장·계단·암·소품 밀도 |
| `camera` | 자유 요·상향 각, 벽 정면에서 허용되는 암, 후퇴율, 1인칭 전환 필요 여부 |
| `check` | 복도 통과·교행·소품 여유, 문 통과·상인방, 천장·카메라 피치, 웅크리기, 계단까지 한 번에 |
| `stairs` | Blondel 2R+T, 한국 건축법, 경사각, CMC 44.765도 정합, 단수·계단참·유효높이 |
| `clutter` | 방 면적·밀도 등급별 소품 개수·종류, ISM/HISM 선택, 삼각형·드로우 추정 |

배경 이론(플레이어·복도·문·계단 실측, 카메라 기하, 환경 스토리텔링, 방 단위 최적화)은
[docs/indoor_exploration_and_spatial_metrics.md](docs/indoor_exploration_and_spatial_metrics.md)에 정리했습니다.

## 차량 에셋 트러블슈팅과 VRAM

차량 18 차종을 2,000대 배치하는 작업은 "폴리곤을 얼마나 줄일까"보다 **어디서 경계를 지킬까**의 문제입니다.
LP 실루엣, 베이크 케이지, 탄젠트 기준, 텍스처 예산 — 네 경계를 수치로 고정하고 검사하는 도구가 함께 있습니다.

```bash
python -m pipeline.vehicle_asset_optimizer formats            # BC 포맷별 실크기(밉 포함)
python -m pipeline.vehicle_asset_optimizer vram --chassis 18 --exterior 4096 --interior 2048
python -m pipeline.vehicle_asset_optimizer packing --resolution 4096
python -m pipeline.vehicle_asset_optimizer explode --demo --axis z --gap 0.02 --unit mm
python -m pipeline.vehicle_asset_optimizer cage --demo
python -m pipeline.vehicle_asset_optimizer checklist
```

```text
차종당 합계    80.00 MiB  x18 = 1,440.0 MiB
  예산 대비  14.1%  |  남는 양 8,800.0 MiB  |  판정 여유
인스턴스 버퍼 2,000 x 256 B = 0.49 MiB
```

| 명령 | 계산하는 것 |
| --- | --- |
| `formats` | BC1~BC7·비압축 포맷의 bpp 와 4096/2048/1024 실크기(밉 포함) |
| `vram` | 차종당·전체 텍스처 상주량, 예산 비율·판정, 절감 시나리오, 인스턴스 버퍼 |
| `packing` | AO/Roughness/Metallic 분리 vs ORM 패킹 절감률 |
| `explode` | 겹치는 부품의 익스플로전 오프셋과 잔여 겹침 검사 |
| `cage` | 케이지 토폴로지·감싸기·여유(0.4~35%)·실루엣 검사 |
| `checklist` | 익스포트·베이크 12단계 체크리스트 |

배경(IsLowPoly 아키텍처, 3면 실루엣, 케이지·익스플로전, MikkTSpace·3c, RTX 3080 예산표)은
[docs/blender_asset_production_troubleshooting_guide.md](docs/blender_asset_production_troubleshooting_guide.md)에 정리했습니다.

## MCP 토큰 최적화

MCP 서버를 여러 개 붙이면 질문하기 전에 도구 정의만으로 수만 토큰이 나갑니다. 이 저장소에는 그 비용을 줄이는
독립 모듈과 가이드가 함께 있습니다(3D 파이프라인과는 무관, 표준 라이브러리만 사용).

```bash
python -m pipeline.mcp_token_optimizer      # 100개 도구 카탈로그 라우팅 데모
```

```text
catalog: 100 tools, baseline definitions = 38,363 tokens

- 열린 버그 이슈 목록을 GitHub에서 뽑아서 Slack으로 알려줘
    selected: github__list_issues, slack__post_message
    tokens: 821 / 38,363  (97.9% saved)

payload: raw JSON -> summary-first
    21,117 -> 99 tokens  (99.5% saved)
```

```python
from pipeline.mcp_token_optimizer import ToolRouter, sample_catalog, prune_tool_definition

router = ToolRouter(sample_catalog())                       # 실제 tools/list 결과로도 구성 가능
routed = router.route("열린 버그를 Slack으로 알려줘", k=2)   # 필요한 도구만 주입
slim = prune_tool_definition(raw_definition)                # JSON Schema 가지치기
```

핵심 수치는 [docs/mcp_token_optimization_guide.md](docs/mcp_token_optimization_guide.md)에 정리했습니다
(2026-11 기준 공식 문서·실측 인용, 토큰 근사치는 비교용).

| 기법 | 측정된 효과 |
| --- | --- |
| 툴 검색/지연 로딩 | 50+ 도구 72K → 8.7K토큰(Anthropic), 131도구 46,273 → 843(Claude Code 실측) |
| 코드 실행(Code Mode) | 150K → 2K(98.7%), API 2,500개 → 약 1,000토큰(Cloudflare) |
| 프롬프트 캐싱 | 캐시 읽기 0.1×(Anthropic), 같은 대화 21턴 기준 −89% |
| 스키마 경량화 | 도구 1개 937 → 237토큰(−75%) |
| 결과 요약·표 변환 | 300행 JSON 21,021 → 96토큰(요약), 표 −82% |

## 테스트

```bash
python -m unittest discover -s tests -v
```

API 키 없이 돌아갑니다(345개). 가짜 GLB를 만들어 GLB 파싱·채널 매핑·ORM 패킹·payload 검증·재시도 로직을 확인하고,
MCP 모듈은 100개 도구 카탈로그로 라우팅 정확도·결정성·스키마 프루닝·페이로드 압축을,
오픈월드 헬퍼는 셀 반경·스트리밍 윈도우·랜드스케이프 정밀도·RVT 메모리·HLOD·체크리스트 점수를,
실내 헬퍼는 카메라 자유 요·허용 암·피치 기하, 공간 판정과 블로커, 계단 비·법규·CMC, 프리셋 정합, 소품 밀도를,
차량 도구(`tests/test_vehicle_asset_optimizer.py`)는 포맷 크기·밉 체인, 함대 예산과 판정, ORM 절감률, 익스플로전 그룹·잔여 겹침, 케이지 여유·실루엣, 문서 정합을,
C++ 예제 검증(`tests/test_cpp_examples.py`)은 헤더 규약·선언↔정의·복제 대응·NetSerialize·문서 링크를 확인합니다.

```bash
python -m unittest tests.test_cpp_examples -v    # C++ 예제만
```

C++ 예제는 컴파일 대신 구조적 정합성을 검사합니다(UHT 없이 CI에서 돌릴 수 있게).

## 사용 전에 알아둘 것

- **생성 서비스 약관과 학습 데이터**: 상용 프로젝트에 쓰기 전에 각 서비스의 라이선스(출력물 소유권, 상업적 이용)를 확인하세요. TRELLIS.2는 MIT지만 의존 패키지(nvdiffrast, nvdiffrec 등)는 별도 라이선스입니다.
- **AI 텍스처의 한계**: 근접 클로즈업에서는 텍스처에 조명 정보가 남거나 UV seam이 보일 수 있습니다. 히어로 에셋은 생성 → 리토폴로지 → 재베이킹(Substance 등) 순서를 권장합니다. 자세한 판단 기준은 문서 1.4절.
- **경로 판단**: UE5 Nanite 정적 프랍은 폴리곤을 줄일 필요가 없습니다(원본 유지). 캐릭터/스키닝, 모바일, 비-Nanite 타깃은 블렌더에서 감면·UV·베이킹이 필수입니다. 판단 기준과 절차는 [docs/blender_pipeline.md](docs/blender_pipeline.md) 0장·3~5장.
- **비용**: Tripo3D는 크레딧 과금입니다. `face_limit`·`texture_quality`가 올라가면 소비량도 올라가므로, 배경 소품은 낮은 설정으로 먼저 테스트하세요.
- **버전**: API 파라미터와 모델명은 2026-11 기준 공식 문서를 따랐습니다. 서비스가 갱신되면 `pipeline/tripo_client.py`의 상수(`DEFAULT_MODEL`, `TEXTURE_VERSION_V35`)와 문서 3.2절을 함께 갱신하세요.
