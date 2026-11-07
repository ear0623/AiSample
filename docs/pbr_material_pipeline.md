# 머티리얼 텍스처를 이용한 고품질 3D 에셋 제작 및 게임엔진 연동 가이드

> 대상: AI로 3D 에셋을 뽑아 UE5에 넣으려는 게임/그래픽스 개발자
> 범위: 텍스처가 왜 분리되어야 하는가(원리) → PBR 맵 설계 → 생성 파이프라인 → 채널 패킹 → UE5 임포트·머티리얼 → 검증
> 기준 시점: 2026-11. Tripo3D 파라미터는 공식 문서(v3 API) 기준이며, 서비스가 바뀌면 3.2절과 `pipeline/tripo_client.py` 상수를 함께 갱신할 것.

---

## 목차

1. [텍스처 디커플링: 왜 조명을 텍스처에서 떼어내야 하는가](#1-텍스처-디커플링)
2. [PBR 맵의 구성과 역할](#2-pbr-맵의-구성과-역할)
3. [최신 AI 생성 파이프라인](#3-최신-ai-생성-파이프라인)
4. [텍스처 채널 패킹 (ORM)](#4-텍스처-채널-패킹-orm)
5. [UE5 임포트와 머티리얼 구성](#5-ue5-임포트와-머티리얼-구성)
6. [품질 검증 체크리스트](#6-품질-검증-체크리스트)
7. [비용과 시간 최적화](#7-비용과-시간-최적화)
8. [문제 해결](#8-문제-해결)
9. [참고 자료](#9-참고-자료)

---

## 1. 텍스처 디커플링

### 1.1 AI 3D 출력물은 두 계열로 나뉜다

| 계열 | 대표 기법 | 텍스처가 담는 것 | 조명과의 관계 |
| --- | --- | --- | --- |
| **라디언스 장(radiance field)** | NeRF, 3D Gaussian Splatting | 각 점에서 "관찰자 방향으로 나가는 빛의 양" | 조명이 **구워져 있다** |
| **표면 파라미터(surface parameters)** | TRELLIS.2, Tripo3D PBR 출력, 전통 모델링 | 표면의 물리적 성질(albedo, roughness, metallic, normal) | 조명과 **독립** |

NeRF/가우시안은 렌더링하면 놀랍도록 사실적이지만, 그 색은 "그 장면, 그 조명에서 찍힌 결과"입니다. 게임 엔진은 반대로 "표면 성질 + 실시간 조명 → 픽셀 색"을 매 프레임 계산합니다. 이 구조 차이를 메우지 않으면, 화면에서 예뻐 보이는 모델이 엔진에 들어가는 순간 무너집니다.

PBR 텍스처를 뽑는 파이프라인의 목적은 하나입니다.

> **관찰된 색에서 "조명의 몫"을 최대한 제거하고, "표면의 몫"만 남긴다.**

### 1.2 조명이 구워지면 생기는 실제 문제

1. **재조명 불가.** 낮/밤, 실내/실외, 다른 씬에 같은 에셋을 놓으면 색이 전부 틀어집니다. Lumen처럼 조명이 실시간으로 바뀌는 환경에서는 더 두드러집니다.
2. **그림자 이중 적용.** 텍스처에 그려진 접지 그림자와 실시간 그림자가 겹쳐 이중 그림자·떠 보임이 생깁니다. 바닥에 붙은 부분이 특히 어색합니다.
3. **알베도 오염.** 밝은 곳에서 찍힌 면은 albedo가 밝게, 그늘진 면은 어둡게 기록됩니다. 그 오브젝트만 돌려놓아도 명암이 표면에 붙어 다닙니다.
4. **머티리얼 조정 불가.** "이 나무 좀 더 거칠게"를 roughness 값으로 못 합니다. 이미 색에 반사가 섞여 있기 때문입니다.
5. **스타일라이즈드 렌더 불가.** 툰/플랫 렌더링은 albedo가 깨끗해야 성립합니다.

3DGS 계열을 게임에 쓰려면 결국 (a) 표면을 재구성하고 (b) 조명 성분을 걷어내고 (c) PBR 파라미터를 추정하는 과정이 필요합니다. 그래서 최신 파이프라인은 처음부터 **지오메트리 생성과 머티리얼 생성을 분리**해서, 최종 산출물을 PBR 텍스처 묶음으로 냅니다.

### 1.3 De-lighting의 원리

픽셀에 찍힌 색은 대략 다음의 곱입니다.

```
L_observed(u,v)  ≈  albedo(u,v) × [ 직접광 + 간접광 + 앰비언트 ]  +  specular(u,v)
```

de-lighting은 여기서 `[...]` 항을 나누어내는 작업입니다. 핵심 성질 두 가지를 이용합니다.

- **크로마는 albedo가 지배한다.** 같은 재질 안에서 색상(hue)은 거의 일정하고, 밝기만 조명에 따라 변합니다. 그래서 색은 유지하고 **휘도 분포**만 정규화하는 접근이 안전합니다.
- **저주파는 조명, 고주파는 재질.** 큰 명암 얼룩(그림자, 그라디언트)은 조명이고, 나뭇결·균열·때 같은 디테일은 albedo입니다. 주파수로 나눠 저주파만 걷어내는 방식이 실무에서 잘 듣습니다.

실무에서 쓰는 순서(비용 대비 효과):

| 방법 | 설명 | 비용 | 품질 |
| --- | --- | --- | --- |
| ① 생성기 내장 de-lighting | Tripo3D v3.5의 `delight` 옵션(기본 켜짐). 레퍼런스 이미지의 조명을 먼저 제거하고 텍스처링 | 0 (옵션) | 중~상 |
| ② 레퍼런스 통제 | 처음부터 균일한 확산광, 그림자 없는 이미지를 입력(스튜디오 조명, 흰 배경) | 낮음 | 상 |
| ③ DCC 재베이킹 | 중립 조명으로 알베도 베이킹(Substance/Bake), 필요하면 주파수 분리 후 저주파 제거 | 중간 | 상 |
| ④ 수작업 리터치 | seam·오염 부위를 페인팅 | 높음 | 최상 |

주의할 점: **금속은 albedo 자체가 반사광**입니다. 금속 표면의 base color는 "반사된 환경의 색"이므로 de-lighting으로 분리하는 것이 원리적으로 어렵습니다. 금속 파트는 `metallic`과 `roughness`를 먼저 바로잡고, albedo는 반사 틴트(F0)로 해석하는 편이 낫습니다.

### 1.4 어디까지 손볼지 정하는 기준

| 용도 | 필요한 수준 | 권장 공정 |
| --- | --- | --- |
| 프로토타입, 회색 박스 대체 | 실루엣만 맞으면 됨 | 원샷 생성 그대로. de-lighting 생략 가능 |
| 배경 소품(원거리) | 재조명에 견딤 | 생성 + `delight` + ORM 패킹. seam은 눈에 안 띄는 선에서 |
| 상호작용 오브젝트, 중거리 | 근접에서도 재질이 설득력 있음 | 생성 → roughness/metallic 보정 → seam 리터치 → ORM |
| 히어로 에셋, 클로즈업 | 텍셀 밀도·UV·재질 모두 통제 | 생성은 **컨셉/베이스로만** 사용. 리토폴로지 → UV 재정리 → 재베이킹 → 수작업 |

AI 생성물을 "최종"으로 쓰는 판단은 대개 이 지점에서 갈립니다. 2M 폴리곤 + 8K 텍스처라도, UV seam이 실루엣 위에 지나가거나 텍스처에 접지 그림자가 남아 있으면 클로즈업에서 바로 티가 납니다.

---

## 2. PBR 맵의 구성과 역할

### 2.1 워크플로: 메탈릭 vs 스페큘러

UE5는 **메탈릭 워크플로**를 표준으로 씁니다. 입력은 `BaseColor / Metallic / Roughness` 세 가지이고, 스페큘러 색을 직접 지정하지 않습니다(비금속은 0.5 고정, 금속은 base color가 F0가 됨). AI 생성 서비스의 PBR 출력도 대부분 이 규격입니다.

### 2.2 맵별 명세

| 맵 | 담는 정보 | 색공간 | 비트 | 권장 해상도 | 실무 메모 |
| --- | --- | --- | --- | --- | --- |
| **BaseColor (Albedo)** | 확산 반사율. 금속은 반사 틴트 | **sRGB** | 8bit RGB | 2K~4K | AO·그림자·하이라이트·스페큘러를 **넣지 않는다**. 순수 0/255는 피하고 0.02~0.9 범위 유지 |
| **Normal** | 탄젠트 공간 법선 | **Linear** | 8bit RGB | 2K~4K | OpenGL(+Y up) / DirectX(−Y) 규약 차이. UE는 DirectX 기준이라 Green 반전 필요할 수 있음 |
| **Roughness** | 미세면 거칠기(0=거울, 1=완전 확산) | **Linear** | 8bit | 1K~2K | "smoothness"로 저장된 소스는 **반전**해야 함. 0.05~0.95 범위가 안전 |
| **Metallic** | 금속성(0 또는 1) | **Linear** | 8bit | 1K~2K | 물리적으로 0.5는 없다. 경계 전이만 예외적으로 허용. 먼지·녹은 0 |
| **Ambient Occlusion** | 간접광 차폐(오목한 곳) | **Linear** | 8bit | 1K~2K | **BaseColor에 굽지 않는다.** 엔진이 별도로 곱한다 |
| **Height / Displacement** | 표면 높이 | **Linear** | 8~16bit | 2K | Nanite Tessellation 또는 POM용. 8bit는 계단이 보임 |
| **Emissive** | 자체 발광 | **sRGB** | 8bit RGB | 1K | HDR 발광은 EXR 또는 머티리얼 배율로 |
| **Opacity / Alpha** | 투명도 | **Linear** | 8bit | 1K | 알파 클리핑이면 Opacity Mask로 |

색공간을 잘못 지정하면 결과가 조용히 틀립니다. sRGB를 켠 roughness는 중간값이 비선형으로 눌려 재질이 번질듯 번들거리고, sRGB를 끈 base color는 어둡고 칙칙해집니다.

### 2.3 자주 하는 실수

1. **AO와 그림자를 albedo에 굽기.** AO는 엔진의 간접광 계산과 곱해져야 하는데, albedo에 미리 넣어두면 두 번 곱해져 과도하게 어두워집니다. 게다가 오브젝트를 움직여도 그늘 방향이 따라다닙니다.
2. **Roughness 반전.** Substance의 "smoothness"와 UE의 "roughness"는 반대입니다. AI 출력은 보통 roughness지만, 외부 툴에서 온 맵은 항상 확인하세요. `texture_packer.py --invert-roughness`로 보정합니다.
3. **Metallic을 회색으로.** 금속 0.4 같은 값은 렌더러에서 "반쯤 금속"이라는 비물리 상태가 됩니다. 틴트가 필요하면 metallic은 0으로 두고 base color로 해결합니다.
4. **노멀맵 강도 2.0.** AI 생성 노멀은 이미 과장된 경우가 많습니다. `NormalStrength`는 1.0에서 시작해 낮추는 방향으로 조정합니다.
5. **텍스처 해상도만 올리기.** 텍셀 밀도가 낮으면 4K로 올려도 흐릿합니다. UV 면적 대비 실제 크기를 먼저 맞추세요.

### 2.4 텍셀 밀도와 UV

| 대상 | 목표 텍셀 밀도 | 1m 오브젝트에 필요한 텍스처 |
| --- | --- | --- |
| 배경 프롭 | 256~512 px/m | 512~1024 px |
| 주요 소품(중거리) | 1024 px/m | 1024~2048 px |
| 히어로(클로즈업) | 2048 px/m 이상 | 4096 px + UDIM 고려 |

UE 기본 텍스처 밀도 지표는 5.12 px/cm(≈512 px/m)입니다. UV는 **겹침 없이**, seam은 실루엣이나 어두운 골에 배치하고, 정규화는 0~1로 유지합니다. AI 생성물은 UV seam이 예측 불가능한 위치에 생기므로, 임포트 후 체커 텍스처로 한 번 훑는 것이 좋습니다.

---

## 3. 최신 AI 생성 파이프라인

### 3.1 전체 흐름

```
[레퍼런스 준비]  실사 촬영 / 2D 생성 / 콘셉트 아트
      │           · 피사체가 화면의 60% 이상, 배경 단순, 균일 조명
      │           · 512px 이상, 20MB 이하(PNG/JPEG/WebP)
      ▼
[지오메트리 생성]  Tripo3D v3.1  /  TRELLIS.2
      │           · geometry_quality, face_limit 결정
      ▼
[머티리얼 생성]   PBR 베이킹 (base_color, metallic, roughness, normal)
      │           · delight로 레퍼런스의 조명 제거
      ▼
[후처리]         채널 분리 → ORM 패킹 → seam/값 검증
      ▼
[엔진]           UE5 Interchange 임포트 → 텍스처 설정 → MI → Nanite
```

### 3.2 Tripo3D API (v3, 모델 v3.1)

Base URL `https://openapi.tripo3d.ai/v3`, 인증은 `Authorization: Bearer <API 키>`. 모든 생성은 **비동기**입니다: POST가 `task_id`를 주고, `GET /tasks/{task_id}`를 폴링합니다.

| 엔드포인트 | 용도 |
| --- | --- |
| `POST /files` | 로컬 이미지/모델 업로드 → `file_token` |
| `POST /generation/image-to-model` | 이미지 → 3D |
| `POST /generation/text-to-model` | 텍스트 → 3D |
| `POST /generation/multiview-to-model` | 여러 뷰 → 3D |
| `POST /models/texture` | 기존 모델 텍스처 재생성/변경 |
| `POST /models/convert` | FBX/GLTF/USDZ 등 변환, 텍스처 분리 |
| `GET /tasks/{task_id}` | 상태·진행률·결과 URL |

#### 주요 파라미터

| 파라미터 | 값 | 의미와 사용법 |
| --- | --- | --- |
| `model` | `v3.1-20260211`(권장), `v3.0-20250812`, `v2.5-20250123` | 최신이 품질·기능 모두 우위. v2.5는 저비용 |
| `geometry_quality` | `standard` / `detailed` | **`detailed`가 Ultra 모드.** v3.0 이상에서만 유효, v2.5에서 쓰면 거부됨 |
| `face_limit` | 정수 | 최대 삼각형 수. 상한은 모델·모드별로 다름(아래 표) |
| `texture` / `pbr` | bool | `pbr=true`면 base_color/metallic/roughness/normal을 함께 생성. `pbr`가 켜지면 `texture`는 자동 true |
| `texture_quality` | `standard` / `detailed` / `extreme`(8K) / `fast` | `extreme`은 크레딧 추가. `fast`는 texture_version v3.5 필요 |
| `texture_version` | `v3.5-20260815` / `v3.0-20250812` / `v2.5-20250123` | 지오메트리와 별개로 텍스처 모델 고정 |
| `delight` | 기본 `true` | 레퍼런스에 구워진 조명 제거. **v3.5 텍스처 모델에서만 읽힘** |
| `auto_size` | bool | 실제 세계 스케일(미터)로 정규화. 게임 씬 배치에 유용 |
| `texture_alignment` | `original_image` / `geometry` | 레퍼런스 색 우선 vs 생성된 형상 우선 |
| `model_seed`, `texture_seed` | 정수 | 같은 시드 = 같은 결과. 지오메트리는 고정하고 텍스처만 바꿀 때 유용 |
| `export_orientation` | `+x` 등 | 후처리 변환을 할 계획이면 **설정하지 말 것**(변환 후 방향이 틀어질 수 있음) |
| `generate_parts` | bool | 편집 가능한 파트 분리. `texture`/`pbr`와 함께 쓸 수 없음 |

#### 폴리곤 상한

| 모드 | v3.1 | v3.0 | v2.5 |
| --- | --- | --- | --- |
| 삼각형 Standard | 1,500,000 | 1,000,000 | 500,000 |
| 삼각형 **Ultra**(`geometry_quality=detailed`) | **2,000,000** | 2,000,000 | — |
| 쿼드(`quad=true`) | 150,000 | 150,000 | — |

게임용 권장 대역은 공식 문서 기준 50,000~100,000(게임 레디), 10,000~50,000(웹/모바일)입니다. Nanite를 쓴다면 이 대역을 넘겨도 되지만, **품질을 좌우하는 것은 폴리곤 수보다 텍스처와 실루엣**이라는 점을 기억하세요. 2M 폴리곤은 조각·직조처럼 텍스처로 표현이 안 되는 깊이에서만 값을 합니다.

#### 비용 추적

task 응답의 `credits_consumed`에 실제 소비 크레딧이 들어옵니다. 이 파이프라인은 이 값을 `manifest.json`에 기록하므로, 배치 실행 후 에셋별 비용을 바로 집계할 수 있습니다. 요금표는 [Billing 문서](https://developers.tripo3d.ai/en/docs/billing)를 참조하세요.

#### 프롬프트 작성

```
나쁨: "A box."
좋음: "A low-poly medieval wooden treasure chest with iron hinges and a rusty lock."
```

형상 + 재질 + 스타일 + 스케일을 한 문장에 넣습니다. `negative_prompt`에는 `"blurry, low quality, broken mesh, floating parts"` 정도를 기본으로. 텍스처 품질을 위해 재질 단어(weathered, brushed metal, matte ceramic)를 명시하는 것이 실제로 효과가 있습니다.

### 3.3 TRELLIS.2 (로컬 GPU)

Microsoft Research의 오픈소스 이미지→3D 모델입니다. MIT 라이선스.

| 항목 | 값 |
| --- | --- |
| 파라미터 | 4B (flow-matching transformer + sparse compression VAE) |
| 표현 | **O-Voxel** — SDF/iso-surface가 아닌 "필드 없는" 희소 복셀. 열린 표면(옷, 잎), 비매니폴드, 내부 폐쇄 구조를 손실 없이 표현 |
| 해상도 | 512³ ~ 1536³ |
| 속도(H100) | 512³ ≈ 3초 / 1024³ ≈ 17초 / 1536³ ≈ 60초 |
| 하드웨어 | **NVIDIA 24GB VRAM 이상**, Linux 전용(A100/H100 검증), CUDA 12.4 권장 |
| 출력 | PBR 텍스처가 포함된 GLB (Base Color, Roughness, Metallic, Opacity) |
| 라이선스 | 모델·코드 MIT (의존 패키지 nvdiffrast, nvdiffrec은 별도) |

TRELLIS.2의 강점은 **재료를 색이 아니라 파라미터로 생성**한다는 점입니다. 즉 처음부터 PBR이므로 de-lighting 문제가 작고, 투명도·얇은 표면 같은 까다로운 토폴로지에서 API 모델보다 유리한 경우가 있습니다. 설치와 실행은 [docs/trellis2_local_setup.md](trellis2_local_setup.md)를 보세요.

### 3.4 로컬 vs API 선택

| 기준 | Tripo3D API | TRELLIS.2 로컬 |
| --- | --- | --- |
| 초기 구축 | 없음(키만) | CUDA/의존성 설치, 24GB GPU, Linux |
| 대량 처리 | 크레딧 종량제, 병렬 확장 쉬움 | GPU 1대 처리량에 묶임, 반복 비용 0 |
| 품질 상한 | Ultra 2M 폴리곤 + 8K 텍스처 | 1536³ 복셀, 폴리곤은 후처리 감축 |
| 재현성 | 모델이 서버에서 갱신될 수 있음 | 가중치 고정 → 결과 재현 가능 |
| 데이터 | 외부 전송 | 로컬에 머묾 |
| 텍스처 제어 | `texture_seed`, `delight`, 재텍스처 API | 파이프라인 코드로 직접 제어 |
| 추천 | 프로덕션 대량, 유지보수 최소화 | 반복 실험, 보안 요구, 커스터마이징 |

두 경로를 섞는 것도 실용적입니다: **대량 배경 소품은 API, 히어로 후보는 로컬에서 여러 번 돌려 선별**.

### 3.5 세트를 만들 때의 일관성

- 같은 캐릭터/세트는 `model_seed`를 고정하고 `texture_seed`만 바꿔 변형을 만듭니다.
- 스타일 문장을 템플릿으로 고정하세요(예: `"stylized hand-painted, thick outlines, desaturated"`).
- 3개 이상의 소품이 한 화면에 붙는다면, 레퍼런스 이미지의 조명 조건을 통일하는 것이 프롬프트 튜닝보다 효과가 큽니다.

---

## 4. 텍스처 채널 패킹 (ORM)

### 4.1 왜 한 장에 합치는가

AO, Roughness, Metallic은 모두 **단일 채널(흑백)** 정보입니다. 따로 두면:

- 텍스처 3장 = 샘플러 3회 + 메모리 3배 + 캐시 미스 증가
- 머티리얼당 텍스처 바인딩 슬롯 소모

RGB 한 장에 합치면 샘플 1회로 세 값을 얻습니다. UE5와 glTF 모두 이 배치를 표준으로 씁니다.

```
        R                G                  B
   Ambient Occlusion   Roughness         Metallic
```

glTF 2.0의 `metallicRoughnessTexture`도 정확히 같은 규약입니다: **G = roughness, B = metallic, R은 미사용**. 즉 glTF의 MR 텍스처에 AO를 R에 채워 넣으면 그대로 ORM이 됩니다. 이 파이프라인이 하는 일이 그것입니다.

> 팀마다 표기가 다를 수 있습니다. `ORM`, `ARM`, `RMA`, `MRA` 등 접미사가 채널 순서를 나타내는 경우가 많으니, 파일명에 반드시 규약을 남기세요(예: `T_Chair_ORM.png`).

### 4.2 8bit vs 16bit, 그리고 압축

| 항목 | 8bit | 16bit |
| --- | --- | --- |
| 채널 단계 | 256 | 65,536 |
| 메모리 | 기준 | 2배 |
| 적합 | 대부분의 게임 에셋 | 넓은 면적의 부드러운 그라디언트(대형 바닥, 스카이) |

게임에서는 8bit가 표준입니다. 밴딩이 보이는 대형 표면만 16bit나 디더링을 고려합니다.

압축은 채널별 특성에 맞춰야 합니다.

| UE Compression Settings | 내부 포맷 | 쓰는 곳 |
| --- | --- | --- |
| `Default` | BC1/BC7 | BaseColor |
| `Normalmap` | BC5(2채널 고정밀) | Normal |
| `Masks` (no sRGB) | BC1/BC3 | ORM, roughness, AO 등 마스크 |

ORM을 `Default`로 두면 sRGB 감마가 걸리고 압축도 마스크용이 아니어서, roughness가 뭉개지고 metallic 경계가 번집니다. **sRGB Off + Masks**가 정답입니다.

### 4.3 패킹할 때 지키는 규칙

1. **모든 입력을 linear로.** 패커는 채널 값을 그대로 옮기므로, 소스에 감마가 섞여 있으면 결과도 틀어집니다.
2. **해상도를 통일.** 서로 다른 해상도는 업스케일 시 흐려지고, 다운스케일 시 디테일이 날아갑니다. `texture_packer.py`는 가장 큰 크기에 맞춰 리샘플합니다.
3. **채널 독립성 확인.** 압축 블록은 RGB를 함께 압축합니다. AO 경계가 아주 날카롭고 roughness가 부드러우면, 한 채널의 고주파가 다른 채널에 링잉을 남길 수 있습니다.
4. **AO가 없으면 255로 채우고 기록.** AO를 안 쓰는 것이지 "가려짐 없음"이 아닙니다. 가능하면 노멀맵에서 AO를 베이킹하거나 DCC에서 한 번 구우세요.
5. **밉맵 경계.** UV가 0/1에 붙어 있으면 밉 생성 시 반대편 텍셀이 섞입니다. 필요하면 패딩(Dilate)을 적용합니다.

### 4.4 사용법

```bash
# glTF의 MR + AO → UE5 ORM
python pipeline/texture_packer.py \
  --metallic-roughness output/chair/textures/T_Chair_metallic_roughness.png \
  --occlusion        output/chair/textures/T_Chair_occlusion.png \
  -o output/chair/textures/T_Chair_ORM.png

# 채널 값 확인 (min/max/mean)
python pipeline/texture_packer.py --verify output/chair/textures/T_Chair_ORM.png
```

`--verify` 출력에서 채널별 평균을 보면 배치 실수를 바로 잡습니다. 예를 들어 roughness 평균이 20 근처로 나오면 거의 거울 같은 재질이 된 것이니, 소스가 smoothness였는지 의심해야 합니다.

---

## 5. UE5 임포트와 머티리얼 구성

### 5.1 포맷 선택: glTF vs FBX

| 기준 | glTF(.glb/.gltf) | FBX |
| --- | --- | --- |
| 임포터 | Interchange(현행 표준) | Interchange(구 FBX 임포터 대체) |
| 재질 | glTF 머티리얼 → Material Instance 자동 생성, 부모 교체 가능 | 임포트 옵션에서 머티리얼 생성 여부 지정 |
| 텍스처 | 임베드 또는 외부 참조 | 임베드 또는 `.fbm/` 폴더로 분리 |
| 스켈레탈/애니메이션 | 지원(제한적) | 가장 안정적 |
| 권장 | 정적 프롭, 배경 | 캐릭터, 애니메이션, 스켈레탈 |

이 파이프라인은 둘 다 뽑습니다. `model.glb`는 원본 보관/검증용, `ue5/`의 FBX는 엔진 임포트용입니다.

### 5.2 임포트 옵션

Interchange 임포트 창에서 확인할 항목:

| 옵션 | 권장 | 이유 |
| --- | --- | --- |
| **Build Nanite** | 고밀도 정적 메시면 On | 폴리곤 수 걱정 없이 넣을 수 있음. 저폴리 소품은 Off |
| Import Materials | On (검증용) | 자동 생성된 MI를 비교 기준으로 사용 |
| Generate Collision | 필요 시 | 원거리 소품은 생략하고 단순 콜리전을 따로 |
| Combine Meshes | On | 조각이 나뉜 채로 들어오면 드로우콜이 늘어남 |
| Import Normals | On | AI 생성 노멀을 살린다. 깨진 경우만 재계산 |
| Generate Lightmap UVs | Nanite + Lumen이면 대개 Off | 동적 GI만 쓰면 라이트맵 불필요 |

### 5.3 텍스처 설정

| 파일 | Compression | sRGB | 비고 |
| --- | --- | --- | --- |
| `*_basecolor` | Default | **On** | BC7(데스크톱) / BC1 |
| `*_normal` | Normalmap | **Off** | BC5. Green 반전 필요 여부 확인 |
| `*_ORM` | Masks | **Off** | BC1/BC3 |
| `*_roughness` / `*_metallic` / `*_occlusion` | Masks | **Off** | 개별 사용 시 |
| `*_height` | Masks 또는 Grayscale | **Off** | 16bit면 Grayscale |

**노멀맵 Green 채널**: glTF는 OpenGL 규약(+Y up), UE는 DirectX 규약입니다. 변환 없이 넣으면 요철이 반대로 보입니다(움푹 들어간 곳이 튀어나옴). `ue5_import.py`는 기본으로 `Flip Green Channel`을 켜고, 파이프라인에서 미리 뒤집은 경우 끄도록 안내합니다.

### 5.4 마스터 머티리얼

하나의 마스터 머티리얼에 파라미터를 뚫고, 에셋마다 Material Instance로 값만 바꾸는 구조가 유지보수에 유리합니다.

노드 구성(의사 코드):

```
BaseColorTex (sRGB)        → Base Color
NormalTex  (Normalmap)     → Normal
ORM        (Masks) ─┬─ Mask(R) ─────────────→ Ambient Occlusion
                    ├─ Mask(G) × RoughScale → Roughness
                    └─ Mask(B) ─────────────→ Metallic
```

파라미터로 뚫어둘 것:

| 파라미터 | 타입 | 용도 |
| --- | --- | --- |
| `BaseColor` / `Normal` / `ORM` | Texture2D | 텍스처 슬롯 |
| `RoughnessScale` | Scalar (기본 1.0) | AI 텍스처의 거칠기 보정 |
| `MetallicScale` | Scalar (기본 1.0) | 금속 파트 미세 조정 |
| `NormalStrength` | Scalar (기본 1.0) | 과장된 노멀 완화 |
| `AOStrength` | Scalar | AO 과다 적용 방지 |
| `UVTiling` | Vector2 | 타일링 |

**AO 처리 주의.** UE5 머티리얼의 `Ambient Occlusion` 입력은 간접광에만 곱해집니다. AO를 Base Color에도 넣으면 이중 적용이 되어 과하게 어두워집니다. 한 곳에만 넣으세요.

### 5.5 Nanite

| 항목 | 내용 |
| --- | --- |
| 대상 | 정적 메시(스켈레탈은 5.5부터 실험적 지원) |
| 이득 | 폴리곤 수가 성능에 거의 영향 없음. 원거리 LOD 팝 없음 |
| 제약 | 반투명 미지원, 마스크드 머티리얼 제한(디더), WPO 비용, 매우 얇은 이중면 주의 |
| 켜는 법 | 임포트 시 `Build Nanite`, 또는 메시 Details > Nanite Settings > Enable |
| 폴리 예산 | AI 출력 1~2M 폴리곤은 Nanite에 적합. 수백만 개 에셋이 씬에 많으면 메모리 확인 |
| 변위 | Nanite Tessellation(`r.Nanite.AllowTessellation=1`, `r.Nanite.Tessellation=1` + 머티리얼의 Displacement) — 실험적 |

Nanite를 쓰면 리토폴로지 부담이 크게 줄어듭니다. 이것이 "AI 고밀도 메시"를 실용적으로 만드는 핵심입니다. 다만 **그림자 캐스터, 콜리전, WPO 애니메이션**은 별도로 확인해야 합니다.

### 5.6 Lumen

- Lumen은 동적 GI이므로 라이트맵 UV가 필요 없습니다. Nanite + Lumen 조합이 AI 에셋에 가장 잘 맞습니다.
- 간접광이 밝은 씬에서는 albedo가 어두운 에셋이 죽어 보입니다. 이때 AO 강도를 낮추고 base color를 약간 올리는 것이 정석입니다.
- 반사가 중요한 금속은 `Roughness`를 0.15~0.4로 두고, 주변 환경(스카이/리플렉션 캡처)이 준비되어 있어야 제대로 보입니다.

### 5.7 임포트 자동화

`pipeline/ue5_import.py`는 UE5 에디터 파이썬에서 실행합니다.

```text
Output Log > Cmd:  py "C:/project/ai3d/pipeline/ue5_import.py"
```

파일 상단의 `ASSET_NAME`, `SOURCE_DIR`, `CONTENT_DIR`, `MASTER_MATERIAL`만 프로젝트에 맞게 고치면, 임포트 → 텍스처 압축 설정 → Material Instance 생성 → Nanite 활성화까지 처리합니다. 엔진 버전에 따라 프로퍼티명이 다를 수 있으므로 첫 실행 로그를 확인하세요.

---

## 6. 품질 검증 체크리스트

에셋 하나를 받았을 때, 엔진에 넣기 전에 확인할 것.

**형상**
- [ ] 실제 스케일이 맞는가(1m 기준 오브젝트와 나란히 배치)
- [ ] 실루엣이 레퍼런스와 일치하는가
- [ ] 뒤집힌 노멀, 구멍(hole), 떠 있는 파편이 없는가
- [ ] 삼각형 수가 예산 안인가(`glb_texture_tools.py info`로 확인)

**텍스처**
- [ ] base color가 sRGB로 설정되었는가
- [ ] roughness/metallic/ORM이 linear + Masks인가
- [ ] 채널 값이 물리적으로 말이 되는가(`--verify`로 평균 확인)
- [ ] AO가 albedo에 구워져 있지 않은가
- [ ] 텍셀 밀도가 씬 기준과 맞는가(체커로 확인)
- [ ] UV seam이 실루엣 위에 지나가지 않는가

**조명 반응**
- [ ] 단일 광원으로 360° 돌려보며 명암이 표면에 붙어 있지 않은가
- [ ] HDRI만 켠 상태에서 금속/비금속 구분이 자연스러운가
- [ ] 그림자가 이중으로 생기지 않는가

**엔진 통합**
- [ ] Nanite/LOD에서 팝이나 깜빡임이 없는가
- [ ] 머티리얼 인스턴스 파라미터가 정상 연결되었는가
- [ ] 드로우콜/텍스처 메모리가 예산 안인가

---

## 7. 비용과 시간 최적화

1. **낮은 설정으로 먼저 검증.** 프롬프트/레퍼런스가 맞는지 `face_limit=50000`, `texture_quality=standard`로 확인하고, 통과한 것만 Ultra/8K로 재생성합니다. 크레딧의 대부분은 이 단계에서 아낄 수 있습니다.
2. **캐시 활용.** 이 파이프라인은 성공한 에셋에 `manifest.json`을 남기고 재실행 시 건너뜁니다(`--force`로만 재생성). 프롬프트를 바꾸지 않았는데 다시 돌리는 일을 막습니다.
3. **시드는 자산이다.** 결과가 좋았으면 `manifest.json`의 `model_seed`/`texture_seed`를 기록해 두세요. 재현과 변형의 기준이 됩니다.
4. **텍스처만 다시 뽑기.** 형상이 마음에 드는데 텍스처만 문제라면 `/models/texture`로 재텍스처링하는 편이 전체 재생성보다 쌉니다.
5. **배치 병렬화.** 현재 스크립트는 순차 처리입니다. 대량이면 프로세스를 여러 개 띄우되, API 요청 한도(429)를 감안해 동시 2~4개 정도로 제한하세요.

---

## 8. 문제 해결

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| GLB에 텍스처가 없다 | `pbr=false` 또는 `texture=false`로 생성 | 요청에 `"pbr": true` 포함. 이미 만든 task는 `/models/texture`로 재텍스처 |
| metallic_roughness만 있고 AO가 없다 | glTF는 AO를 별도 슬롯에 두며, 생성기가 안 만들기도 함 | ORM R을 255로 두고 사용, 또는 DCC에서 AO 베이킹 |
| roughness가 금속처럼 번들거린다 | smoothness 소스를 반전 없이 사용 / sRGB On | `--invert-roughness`, 텍스처 sRGB Off 확인 |
| 임포트 후 재질이 분홍(체커) | 머티리얼/텍스처 참조 깨짐 | 마스터 머티리얼 경로, MI 파라미터 이름 확인 |
| 요철이 반대로 보인다 | 노멀 Green 채널 규약 불일치 | 텍스처에서 `Flip Green Channel` |
| 에셋이 너무 어둡다 | AO 이중 적용(base color + AO) | AO를 base color에서 제거 |
| Nanite에서 일부가 사라진다 | 반투명/마스크드 머티리얼 | Opacity Mask 사용, 블렌드 모드 Opaque로 |
| UV가 늘어나 보인다 | 텍셀 밀도 불균형, UV 스케일 | UV 재정리 또는 타일링으로 보정 |
| API가 `1004`를 돌려준다 | 파라미터 조합 오류 | `texture_quality=fast`/`delight`는 `texture_version=v3.5-20260815` 필요. `generate_parts`는 `texture=false` 필요 |
| task가 오래 `running`이다 | 큐 대기 또는 서버 혼잡 | `--timeout`을 늘리고 `status <task_id>`로 재조회. 중복 제출 금지 |
| FBX 임포트 후 텍스처가 안 붙는다 | `.fbm` 폴더가 FBX 옆에 없음 | zip을 풀 때 폴더 구조를 유지 |

---

## 9. 참고 자료

- Tripo3D 개발자 문서 — 이미지→3D (H 시리즈): https://developers.tripo3d.ai/en/docs/generation-image-to-model/standard
- Tripo3D — Task Query: https://developers.tripo3d.ai/en/docs/task-query
- Tripo3D — Model Convert (FBX/GLTF, 텍스처 분리): https://developers.tripo3d.ai/en/docs/models-convert
- Tripo3D — File Upload: https://developers.tripo3d.ai/en/docs/files
- Tripo3D — Texture (재텍스처, delight): https://developers.tripo3d.ai/en/models/texture
- Tripo3D — Billing: https://developers.tripo3d.ai/en/docs/billing
- TRELLIS.2 (Microsoft) — GitHub: https://github.com/microsoft/TRELLIS.2
- TRELLIS.2-4B — Hugging Face: https://huggingface.co/microsoft/TRELLIS.2-4B
- TRELLIS.2 — 논문: https://arxiv.org/abs/2512.14692
- glTF 2.0 명세 (metallicRoughness, normal/occlusion 텍스처 규약): https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
- Unreal Engine — Nanite: https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine
