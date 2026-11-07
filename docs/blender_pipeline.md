# 블렌더에서의 AI 3D 에셋 가공: 리토폴로지 · UV · Cycles 베이킹 · 엔진 익스포트

> 대상: AI로 뽑은 고밀도 3D 에셋을 **캐릭터/리깅/애니메이션 또는 모바일·비-Nanite 환경**에 넣으려는 게임/그래픽스 개발자
> 범위: 임포트 주의점 → 원본 검사 → 폴리곤 감면·리토폴로지 → UV·케이지 → Cycles 하이폴리→로우폴리 베이킹 → 머티리얼 → 엔진 익스포트
> 기준 시점: 2026-11. Blender **3.6 LTS / 4.x / 5.x** 기준. 4.1(Auto Smooth 제거), 4.2(EEVEE Next), 5.0(노드 항상 사용)의 API 변경을 반영했고, 현재 LTS는 5.2 계열이다.
> 함께 쓰는 파일: [`pipeline/blender_import.py`](../pipeline/blender_import.py) · [`docs/pbr_material_pipeline.md`](pbr_material_pipeline.md)

---

## 목차

0. [한눈에: 폴리곤을 줄여야 하는가?](#0-한눈에-폴리곤을-줄여야-하는가)
1. [임포트: AI 생성 메시에서 먼저 확인할 것](#1-임포트-ai-생성-메시에서-먼저-확인할-것)
2. [고밀도 원본 검사](#2-고밀도-원본-검사)
3. [폴리곤 감면과 리토폴로지](#3-폴리곤-감면과-리토폴로지)
4. [UV 언랩과 베이킹 케이지](#4-uv-언랩과-베이킹-케이지)
5. [Cycles 하이폴리 → 로우폴리 베이킹](#5-cycles-하이폴리--로우폴리-베이킹)
6. [머티리얼 노드 구성과 색공간](#6-머티리얼-노드-구성과-색공간)
7. [스무스 셰이딩과 노멀](#7-스무스-셰이딩과-노멀)
8. [게임 엔진으로 익스포트](#8-게임-엔진으로-익스포트)
9. [자동화 스크립트 사용법](#9-자동화-스크립트-사용법)
10. [체크리스트](#10-체크리스트)
11. [문제 해결](#11-문제-해결)
12. [참고 자료](#12-참고-자료)

---

## 0. 한눈에: 폴리곤을 줄여야 하는가?

AI 생성 결과물( Tripo3D Ultra 200만 삼각형, TRELLIS.2 수십만~수백만 )은 **원본 그대로는 게임 런타임에 넣을 수 없다**는 것이 기본 전제다. 단, 예외가 하나 있다: **UE5 Nanite 정적 프랍**.

```
AI 생성 고밀도 메시 (GLB / FBX)
        │
        ├─ Q1. 스켈레탈 메시인가? (캐릭터, 리깅, 애니메이션)
        │        └─ 예 ──────────────────────────────► 경로 B (감면·리토폴로지 필수)
        │
        ├─ Q2. 모바일 / 콘솔 / 유니티 / 웹 / VR처럼
        │       Nanite를 쓸 수 없는 타깃인가?
        │        └─ 예 ──────────────────────────────► 경로 B
        │
        ├─ Q3. 실루엣·콜리전이 성능 예산에 걸리는가?
        │       (수백 개 인스턴스, 그림자 캐스터, LOD 필요)
        │        └─ 예 ──────────────────────────────► 경로 B (또는 Nanite + LOD 병행)
        │
        └─ 그 외: UE5 Nanite 정적 프랍 (배경, 소품, 건축 요소, 데칼용 메시)
                 └────────────────────────────────► 경로 A (감면하지 않음)
```

| | 경로 A — Nanite 직결 | 경로 B — 감면 + 베이킹 |
| --- | --- | --- |
| 대상 | 정적 프랍, 배경, 건축 요소 | 캐릭터/스키닝, 모바일, 비-Nanite, LOD·콜리전 |
| 폴리곤 | 원본 유지(수십만~200만) | 목표 삼각형 수로 감면(5k / 10k / 30k 등) |
| 블렌더에서 하는 일 | 임포트 → 머티리얼 정리 → 스케일/원점 → (선택) FBX/GLB 변환 | 임포트 → 검사 → 리토폴로지 → UV → 케이지 → 베이킹 → 머티리얼 → 익스포트 |
| 디테일 보존 | 메시 자체가 디테일 | 노멀맵/AO/러프니스로 이전 |
| 이 문서 | 1·2·6·7·8장 | **3·4·5장이 핵심**, 전 장 |
| 스크립트 | `--model ... --export-fbx ...` | `--target-tris 30000 --bake normal,ao,roughness,basecolor` |

**경로 A에서도 블렌더를 쓰는 이유**: Nanite는 폴리곤 수를 감춰 주지만, ①AI 메시의 깨진 노멀·중복 버텍스 ②스케일·원점 ③머티리얼/색공간 ④불필요한 내부 면(속이 빈 메시)은 정리해야 한다. 스크립트의 임포트/정리/머티리얼 부분만 쓰면 된다.

**경로 B의 핵심 판단**: Decimate는 "삼각형을 줄이는" 도구이지 "애니메이션 가능한 토폴로지를 만드는" 도구가 아니다. 캐릭터는 **리토폴로지(쿼드 흐름) → Decimate로 마무리 → 베이킹** 순서다. Decimate만 돌린 캐릭터는 팔꿈치·무릎에서 접히지 않고, UV도 찢어진다.

---

## 1. 임포트: AI 생성 메시에서 먼저 확인할 것

### 1.1 포맷 선택

| | glTF(.glb) | FBX |
| --- | --- | --- |
| 이 파이프라인에서 | Tripo3D 원본. PBR 맵이 임베드됨 | `--ue5` 변환 결과. 텍스처가 `.fbm/`에 분리 |
| 블렌더 임포터 | `bpy.ops.import_scene.gltf` | `bpy.ops.import_scene.fbx` |
| 축 처리 | +Y up → Blender +Z up **자동 변환** | `axis_forward='-Z'`, `axis_up='Y'` 지정 |
| 머티리얼 | Principled BSDF + Image Texture 자동 구성 | 임포트 옵션에 따라 구성/생략 |
| 권장 | 원본 보관, 검증, 베이킹 소스 | 엔진 호환, 스키닝 |

```python
# 스크립트가 쓰는 임포트 호출 (참고)
bpy.ops.import_scene.gltf(filepath=str(glb))
bpy.ops.import_scene.fbx(
    filepath=str(fbx), use_custom_normals=True, global_scale=1.0,
    apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
    axis_forward="-Z", axis_up="Y",
)
```

### 1.2 스케일

- glTF는 **1 unit = 1 m** 규약이지만, 생성 서비스가 실제 크기를 보장하지 않는다. Tripo3D는 `--auto-size`로 미터 정규화를 요청할 수 있지만 결과는 모델마다 다르다.
- FBX는 임포트 시 `Apply Unit Scale`과 `Scale`(기본 1.0)을 확인한다. 다른 DCC에서 cm 단위로 내보낸 FBX는 100배 차이가 난다.
- 확인법: 오브젝트 선택 → `N` 패널 → Dimensions. 캐릭터라면 키가 1.6~1.9 m, 의자라면 0.8~1.0 m 근처여야 한다.
- 스크립트: `--scale-target 1.8` → 최대 치수를 1.8 m로 정규화하고 회전/스케일을 메시에 적용(transform apply)한다. **엔진에서 스케일 1로 두는 것이 목표**다.

### 1.3 노멀과 토폴로지

AI 생성 메시에서 흔한 상태:

| 증상 | 원인 | 대응 |
| --- | --- | --- |
| 표면이 각져 보임 / 음영이 깨짐 | 정점이 붙지 않은 삼각형 더미(triangle soup), 커스텀 노멀 | Merge by Distance(0.0001) → `Shade Smooth by Angle` → 필요 시 노멀 재계산 |
| 안쪽이 보임 / 법선 반전 | 닫히지 않은 메시, 뒤집힌 면 | `bmesh.ops.recalc_face_normals`, Backface Culling으로 확인 |
| 구멍이 뚫려 보임 | 생성 메시의 얇은 부분, 비매니폴드 | Voxel Remesh로 막거나, 구멍 주변을 Fill |
| 실루엣이 울퉁불퉁 | 저해상도 생성, 노이즈 | Sculpt Smooth, Remesh 후 재구성 |

- glTF 임포터는 **임베드된 노멀을 커스텀 스플릿 노멀로** 가져온다. AI 노멀이 깨졌다면 `--recalc-normals`로 재계산하는 편이 낫다.
- **중복 버텍스 병합은 감면·UV보다 먼저** 해야 한다. 병합하지 않으면 Decimate가 이음매를 따라 갈라지고, UV 아일랜드가 조각난다.

### 1.4 UV와 머티리얼

- Tripo3D GLB는 UV와 PBR 텍스처가 들어 있다. 다만 UV는 **자동 아틀라스**라 텍셀 밀도가 고르지 않고, 리토폴로지 후에는 그대로 쓸 수 없다.
- 재질이 여러 개면 이름이 `m0_basecolor`, `m1_basecolor`처럼 나뉜다. 스크립트는 이 접두사를 읽어 슬롯별로 텍스처를 배정한다.
- glTF 임포터가 만든 Principled 노드는 대개 정상이지만, **ORM을 개별 채널로 분리하지 않고 한 장으로 꽂거나**, AO를 Principled에 직접 연결하려다 실패한 상태가 흔하다. 6장에서 다시 구성한다.

---

## 2. 고밀도 원본 검사

감면 전에 원본을 수치로 기록해 둔다. 스크립트는 임포트 직후 자동으로 검사하고 JSON 리포트에 남긴다.

| 항목 | 보는 이유 | 기준(예시) |
| --- | --- | --- |
| 삼각형 수 | 감면 목표와 ratio 계산 | Ultra 1~2M, standard 5만~20만 |
| 버텍스 수 | 삼각형 수와 비슷하면 대부분 언웰드 | 삼각형의 0.5~1배 |
| 비매니폴드 엣지 | 베이킹·불리언·리깅 실패 원인 | 0에 가까울수록 좋음. 많으면 Voxel Remesh |
| 퇴화 면(면적≈0) | 노멀/베이킹 아티팩트 | 0 권장. `Merge by Distance` 후 재확인 |
| N-gon | Decimate/UV 품질 저하 | AI 메시는 대부분 삼각형. N-gon은 Quadriflow 후 발생 |
| UV 레이어 | 베이킹 대상 UV 존재 여부 | 로우폴리는 새로 만들어야 함 |
| 머티리얼 수 | 베이킹은 슬롯별로 해야 함 | 1개가 이상적. 많으면 합치기 검토 |
| 커스텀 노멀 | 깨진 노멀 고정 | 재계산 또는 Clear Custom Split Normals |
| 셰이프 키 | 감면 시 보존 불가 | 있다면 감면 전에 적용/삭제 결정 |

```text
[ai3d]   검사 Hero: 1,204,388 삼각형 / 1,310,552 버텍스 / 비매니폴드 0 엣지 / UV 1 / 머티리얼 1
```

> **원본은 지우지 않는다.** 스크립트는 `Hero_High`로 이름을 바꿔 보존하고 `Hero_Low` 사본을 만든다. 베이킹이 마음에 안 들면 하이폴리로 다시 굽는다.

---

## 3. 폴리곤 감면과 리토폴로지

### 3.1 목표 삼각형 수 정하기

프로젝트 기준 예시(절대 기준이 아니라 예산표를 먼저 정한다):

| 용도 | 삼각형 예산(예시) | 비고 |
| --- | --- | --- |
| 모바일 히어로 캐릭터 | 15k~30k | 스키닝 4본/정점 이하, 텍스처 1~2K |
| PC/콘솔 히어로 캐릭터 | 60k~120k | 4K 텍스처, LOD 2~3단 |
| PC 조연/몬스터 | 20k~50k | |
| 배경 프랍(비-Nanite) | 2k~10k | |
| Nanite 프랍 | 제한 없음(원본 유지) | 경로 A |

스크립트는 `--target-tris 30000`처럼 **삼각형 수**로 받고, 내부에서 `ratio = 목표 / 현재`를 계산해 Decimate에 넣는다. Decimate는 근사치라 결과가 ±5% 벗어날 수 있으므로 리포트의 `achieved_tris`를 확인하고 필요하면 `--decimate 0.024`처럼 비율로 미세 조정한다.

### 3.2 Decimate (Collapse) — 빠른 감면

가장 빠르고 예측 가능한 방법. **정적 프랍, LOD, 리토폴로지 후 마무리**에 적합하다.

```python
mod = obj.modifiers.new("Decimate", "DECIMATE")
mod.decimate_type = "COLLAPSE"
mod.ratio = 0.08                 # 남길 삼각형 비율
mod.use_collapse_triangulate = True
mod.use_symmetry = True          # 캐릭터 좌우 대칭 유지 (선택)
mod.symmetry_axis = "X"
bpy.ops.object.modifier_apply(modifier=mod.name)
```

실무 포인트:

- **Ratio 계산**: 120만 → 3만이면 `3/120 = 0.025`. 목표 삼각형 수를 직접 넣는 편이 안전하다(스크립트의 `--target-tris`).
- **대칭**: 캐릭터는 `use_symmetry`를 켜야 좌우가 따로 무너지지 않는다. 단, 메시가 실제로 X=0 대칭이고 원점이 중앙에 있어야 한다.
- **보존 영역**: 얼굴·손처럼 디테일이 필요한 곳은 Vertex Group을 만들고 `modifier.vertex_group`에 지정하면 덜 깎인다(Weight 0~1).
- **UV**: Collapse는 UV를 보간해 유지하지만 품질은 떨어진다. 베이킹을 위해 새 UV를 만들 것이므로 크게 신경 쓰지 않아도 된다.
- **셰이프 키/아마추어**: Decimate는 셰이프 키를 보존하지 못하고, 이미 리깅된 메시에 적용하면 웨이트가 왜곡된다. **리깅 전에** 감면한다.

### 3.3 Remesh — 토폴로지 흐름 다시 잡기

Decimate는 삼각형을 줄일 뿐 **쿼드 흐름(edge loop)을 만들지 않는다**. 애니메이션 가능한 토폴로지가 필요하면 Remesh 계열을 쓴다.

#### Voxel Remesh

- 균일한 사각형에 가까운 표면을 새로 만든다. 구멍·자기교차를 정리하고 스컬프팅 기반을 만들 때 좋다.
- **UV, 날카로운 모서리, 얇은 판(천, 잎)은 모두 사라진다.** 반드시 사본에서 작업한다.
- Voxel Size는 모델 높이의 1/100~1/300 정도에서 시작한다(1.8 m 캐릭터 → 0.006~0.018).

```python
mod = obj.modifiers.new("Remesh", "REMESH")
mod.mode = "VOXEL"
mod.voxel_size = 0.01
bpy.ops.object.modifier_apply(modifier=mod.name)
```

#### Quadriflow Remesh

- 삼각형/복셀 결과를 **쿼드 중심 토폴로지**로 다시 만든다. 목표 면 수를 지정할 수 있다.
- 100만 폴리곤 원본에 바로 돌리면 매우 느리다. **Voxel Remesh나 Decimate로 5만~10만 수준으로 줄인 뒤** 돌린다.
- 얼굴/손 디테일은 보존되지 않으므로, 리토폴로지 결과를 다시 스컬프트하거나 노멀 베이킹으로 살린다.

```python
bpy.ops.object.quadriflow_remesh(target_faces=8000, use_mesh_symmetry=True)
```

#### 캐릭터 권장 순서

```
원본(High, 1.2M)
  └─ Voxel Remesh (0.01)          # 구멍/자기교차 정리, 20만~40만
      └─ Decimate 0.3             # 6만~12만, Quadriflow 부담 감소
          └─ Quadriflow (8k~15k)   # 쿼드 흐름
              └─ Sculpt 터치업     # 얼굴, 손, 옷 주름
                  └─ Decimate 0.8  # 최종 예산 맞춤(삼각화)
                      └─ UV → 베이킹
```

### 3.4 수동 리토폴로지 (품질 우선)

히어로 캐릭터는 자동화로 끝내지 않는다. 블렌더 기본 도구만으로도 가능하다:

1. **Shrinkwrap** 모디파이어를 리토폴로지 메시에 걸고 Target을 하이폴리로 지정 → 표면에 붙어서 작업.
2. **Poly Build** 툴(E)로 큰 면부터 채우고, **Snap to Face**로 버텍스 배치.
3. 관절(어깨·팔꿈치·무릎·손목)에 **3개 이상의 엣지 루프**를 만든다. 굽힐 때 무너지지 않는 최소 조건이다.
4. 얼굴은 눈·입 주변 루프를 방사형으로, 손은 손가락마다 2~3 루프.
5. 대칭은 **Mirror 모디파이어 + Clipping**으로 절반만 작업한다.
6. Quad Remesher(유료 애드온), RetopoFlow(유료)는 속도를 크게 높인다. 라이선스는 프로젝트 정책에 맞게.

> **자동 vs 수동 판단**: 화면에서 30 cm 이상 떨어져 보이는 조연/몬스터는 Quadriflow + Decimate로 충분하다. 얼굴 클로즈업이 있는 히어로만 수동 리토폴로지에 시간을 쓴다.

### 3.5 리깅 전 확인

- [ ] Transform 적용됨(Scale 1, Rotation 0)
- [ ] 원점이 발바닥 중앙(`--origin bottom`)
- [ ] 중복 버텍스 병합, 비매니폴드 0
- [ ] 관절 엣지 루프 확보, 좌우 대칭
- [ ] UV 존재(베이킹/텍스처링용)
- [ ] 셰이프 키/모디파이어 정리(Apply 또는 순서 확인)

리깅 후 LOD를 만들 때는 **Data Transfer 모디파이어**로 원본의 버텍스 그룹(웨이트)을 로우폴리에 전이한다. 수동으로 다시 칠하는 것보다 빠르고 일관적이다.

---

## 4. UV 언랩과 베이킹 케이지

### 4.1 로우폴리 UV

베이킹은 **로우폴리의 UV**에 하이폴리의 표면 정보를 기록한다. 따라서 로우폴리 UV가 먼저 있어야 한다.

| 방법 | 적합 | 비고 |
| --- | --- | --- |
| Smart UV Project | 프랍, 빠른 프로토타입 | 아일랜드가 많고 seam이 눈에 띔. 캐릭터에는 부적합 |
| 수동 seam + Unwrap | 캐릭터, 히어로 | 얼굴/손/옷 경계에 seam, `Average Island Scale` |
| 기존 UV 유지 | 하이폴리 UV를 그대로 쓸 때 | 감면 후 왜곡. 텍셀 밀도 불균일 |

스크립트는 `--unwrap auto|smart|keep`을 제공한다. `auto`는 UV가 없을 때만 Smart UV Project를 돌리고, 기존 UV가 있으면 경고를 남긴다(캐릭터는 수동 언랩 권장).

수동 언랩 순서:

1. Edit Mode → Edge Select → seam 표시(눈/입/귀 뒤, 겨드랑이, 손목, 발목, 옷 경계).
2. `U` → Unwrap (Angle Based).
3. `UV Editor → UV → Average Island Scale`로 텍셀 밀도 통일.
4. `Pack Islands`(margin 0.01~0.02).
5. 텍셀 밀도 확인: 2K 텍스처에서 캐릭터 512~1024 px/m가 일반적. 얼굴은 더 높게.

### 4.2 베이킹 케이지

하이폴리와 로우폴리의 실루엣이 다르면, 로우폴리 노멀에서 나간 광선이 하이폴리에 닿지 않아 **검은 얼룩/노멀 누출**이 생긴다. 케이지(cage)는 로우폴리를 바깥으로 부풀린 껍데기로, 광선의 시작점을 바깥에 두어 이 문제를 줄인다.

```python
# 로우폴리 사본을 노멀 방향으로 extrusion만큼 부풀린 케이지
bmesh.ops...  # (스크립트 build_cage가 자동 수행)
bake.use_cage = True
bake.cage_object = cage_obj
```

- 두께: 모델 크기의 **0.5~2%**에서 시작(1.8 m 캐릭터 → 9~36 mm). 스크립트 기본값은 1%.
- 케이지는 렌더에 보이지 않게 두고, 익스포트 대상에서 제외한다.
- 케이지 없이 `Cage Extrusion` 값만으로도 대부분 해결된다. 아티팩트가 남을 때 실제 케이지 오브젝트를 쓴다.

---

## 5. Cycles 하이폴리 → 로우폴리 베이킹

### 5.1 준비

- 렌더 엔진을 **Cycles**로 바꾼다. EEVEE는 베이킹을 지원하지 않는다.
- 하이폴리와 로우폴리를 같은 위치에 둔다(스크립트는 사본을 만들어 자동으로 겹친다).
- 로우폴리에 UV, 하이폴리에 텍스처/머티리얼이 준비되어 있어야 한다.
- 머티리얼 슬롯이 여러 개면 **모든 슬롯에 같은 베이크 타깃 이미지 노드를 물려야** 한다. 하나라도 비어 있으면 Blender가 베이킹을 중단한다(스크립트는 자동으로 물린다).
- **선택 순서**: 로우폴리를 먼저 선택하고, 하이폴리를 Shift로 추가 선택한 뒤, **로우폴리를 Active**로 만든다. (베이크는 Active 오브젝트의 UV/이미지에 기록된다)
- 로우폴리 머티리얼에 **Image Texture 노드를 만들고 이미지를 지정한 뒤, 그 노드를 클릭해 Active로 만든다.** 베이크 대상은 이 노드의 이미지다.

### 5.2 베이크 종류와 설정

| 베이크 | Bake Type | Pass | 용도 | 설정 |
| --- | --- | --- | --- | --- |
| 노멀 | `NORMAL` | — | 하이폴리 미세 굴곡 | `Normal Space: Tangent`, margin 8~16 |
| AO | `AO` | — | 접힌 곳 음영, 엔진 AO | samples 64~256 |
| 러프니스 | `ROUGHNESS` | — | 재질 거칠기 전이 | Non-Color |
| 베이스컬러 | `DIFFUSE` | `Color`만 | 색 전이 | Direct/Indirect 끔, sRGB |
| 메탈릭 | `EMIT` | — | 베이크 타입이 없어 Emission 트릭 | Non-Color |

공통 설정:

| 설정 | 값 | 설명 |
| --- | --- | --- |
| Selected to Active | On | 하이폴리에서 로우폴리로 광선을 쏜다 |
| Cage / Cage Extrusion | On 또는 1% | 4.2절 |
| Max Ray Distance | 0 (케이지 사용 시) | 케이지 없으면 모델 크기의 2~5% |
| Margin | 8~16 px (2K) | UV 아일랜드 경계 번짐 방지 |
| Use Clear | On | 이전 베이크 잔상 제거 |
| Samples | Normal 16~32, AO 64~256 | 노멀은 노이즈가 거의 없다 |

### 5.3 단계별 절차 (수동)

1. **하이폴리 준비**: 원본 이름 `Hero_High`, 텍스처 연결 확인. 숨기지 말 것(베이크 광선이 닿아야 함).
2. **로우폴리 준비**: `Hero_Low`, Decimate/Quadriflow 완료, Transform 적용.
3. **UV**: 로우폴리 언랩(4.1절).
4. **이미지 생성**: 2K(캐릭터 히어로는 4K). 노멀/AO/러프니스/메탈릭은 `Non-Color`, 베이스컬러만 `sRGB`.
5. **머티리얼**: 로우폴리 머티리얼에 Image Texture 노드 추가 → 이미지 지정 → 노드 선택(Active).
6. **선택**: 로우폴리 Active + 하이폴리 함께 선택.
7. **Render Properties → Bake**:
   - Normal: `Normal Space Tangent`, `Selected to Active` On, Cage 설정 → **Bake**.
   - AO: type AO, samples 128 → Bake.
   - Roughness: type Roughness → Bake.
   - Base Color: type Diffuse, `Direct`/`Indirect` Off, `Color` On → Bake.
   - Metallic: 하이폴리 머티리얼의 Metallic 출력을 Emission으로 임시 연결 → type Emit → Bake → 원복.
8. **저장**: 각 이미지 `Image → Save As`(PNG, 8bit). 파일명 규칙 `T_Hero_Low_normal.png` 등.
9. **검증**: 5.5절.

> **왜 AO를 Base Color에 굽지 않는가**: 엔진에서 AO는 간접광에만 곱해야 한다. Base Color에 구워 버리면 라이팅과 이중 적용되어 어두워진다. 블렌더 프리뷰에서만 곱해서 보고, 최종 머티리얼에서는 AO를 별도 슬롯/텍스처로 넘긴다.

### 5.4 스크립트로 자동화

```bash
blender --background --factory-startup --python pipeline/blender_import.py -- \
  --model output/hero/model.glb \
  --target-tris 30000 \
  --bake normal,ao,roughness,basecolor \
  --bake-size 2048 \
  --unwrap auto \
  --export-fbx output/hero/hero_low.fbx \
  --blend output/hero/hero.blend
```

스크립트가 하는 일:

1. 하이폴리 임포트 → `Hero_High` 보존
2. `Hero_Low` 사본 생성 → `--target-tris`로 Decimate
3. 로우폴리 UV 준비(없으면 Smart UV Project)
4. 로우폴리를 1% 부풀린 케이지 생성
5. Cycles로 normal/ao/roughness/basecolor/metallic 베이킹
6. 베이킹 결과로 로우폴리 최종 머티리얼 재구성
7. FBX/GLB 익스포트, `.blend` 저장(텍스처 pack), JSON 리포트

메탈릭은 `EMIT` 트릭을 스크립트가 자동으로 처리한다(하이폴리 머티리얼의 Metallic → Emission → Bake → 원복).

### 5.5 베이크 결과 검증

| 맵 | 정상 | 비정상 |
| --- | --- | --- |
| Normal | 전체가 보라/파랑(128,128,255) 계열, 요철이 보임 | 새까맘 or 한 색으로 평평 → UV/선택/케이지 문제 |
| AO | 대부분 밝고 접힌 곳만 어두움 | 전체가 어두움 → ray distance 과다, 노멀 반전 |
| Roughness | 회색조, 금속/비금속 차이 | 0 또는 1로 뭉침 → 하이폴리 러프니스 미연결 |
| Base Color | 원본과 유사, seam 없음 | 검은 seam → margin 부족, UV 아일랜드 겹침 |
| Metallic | 금속 부분만 흰색 | 전체 검정 → Emission 연결 실패 |

추가 확인:

- 로우폴리에 베이크 맵을 물리고 → 하이폴리를 숨기고 → 뷰포트에서 실루엣/디테일 비교.
- 노멀맵은 **Tangent space, +Y(OpenGL)**. UE5/Unity(DirectX 계열)로 갈 때 Green 채널을 뒤집는다(8장).
- 2K에서 margin 8 px 이하이면 밉맵 단계에서 seam이 보인다.

---

## 6. 머티리얼 노드 구성과 색공간

### 6.1 Principled BSDF 3.x vs 4.x

Blender 4.0에서 Principled BSDF가 v2로 바뀌며 소켓 이름이 달라졌다. 스크립트는 이름 후보를 순서대로 찾아 양쪽을 지원한다.

| 역할 | 3.x 소켓 | 4.x/5.x 소켓 |
| --- | --- | --- |
| 기본색 | Base Color | Base Color |
| 금속성 | Metallic | Metallic |
| 거칠기 | Roughness | Roughness |
| 노멀 | Normal | Normal |
| 발광 | Emission | Emission Color |
| 발광 세기 | Emission Strength | Emission Strength |
| 투명도 | Alpha | Alpha |
| 스페큘러 | Specular | Specular IOR Level |
| 클리어코트 | Clearcoat | Coat Weight |
| 서브서피스 | Subsurface | Subsurface Weight |

**AO 입력은 3.x·4.x·5.x 모두 Principled에 없다.** AO는 Base Color에 곱하거나(프리뷰용), 엔진 머티리얼의 AO 슬롯으로 넘긴다. 스크립트 기본값은 `--ao-mode multiply`(프리뷰 충실도), 엔진용은 `keep`으로 노드만 남긴다.

### 6.2 ORM / metallic_roughness 노드 구성

```
[ORM.png]  Non-Color
   └─ Image Texture ─ Color ─▶ Separate Color
                                 ├─ Red   ──▶ (AO: Base Color와 Multiply 또는 미연결)
                                 ├─ Green ──▶ Roughness (× RoughnessScale)
                                 └─ Blue  ──▶ Metallic  (× MetallicScale)

[Normal.png] Non-Color
   └─ Image Texture ─ Color ─▶ Normal Map (Tangent, Strength) ─▶ Normal

[BaseColor.png] sRGB
   └─ Image Texture ─ Color ─▶ Base Color
```

- glTF `metallic_roughness`는 **G=Roughness, B=Metallic, R=사용 안 함**. ORM은 **R=AO, G=Roughness, B=Metallic**. 채널 배치는 같고 R의 의미만 다르다.
- 개별 `roughness`/`metallic`/`occlusion` 텍스처가 있으면 해당 채널만 덮어쓴다(스크립트 `plan_channels`).
- `Separate Color`는 Blender 3.3+ 노드다. 3.0~3.2는 `Separate RGB`(출력 R/G/B)를 쓴다.

### 6.3 색공간(Color Space) — 가장 흔한 실수

| 텍스처 | Color Space | 이유 |
| --- | --- | --- |
| Base Color, Albedo, Diffuse | **sRGB** | 색 데이터. 감마 변환 필요 |
| Emissive | **sRGB** | 색 데이터 |
| Normal | **Non-Color** | 벡터 데이터. 감마가 적용되면 요철 방향이 틀어짐 |
| Roughness / Metallic / AO / ORM | **Non-Color** | 0~1 스칼라. 감마 적용 시 값이 왜곡됨 |
| Height / Displacement | **Non-Color** | 스칼라 |
| Mask / Opacity | **Non-Color** | 스칼라 |

확인: Image Texture 노드 선택 → Image Editor 사이드바 → Color Space. 또는 `image.colorspace_settings.name`.
`Non-Color`는 "Raw"의 현대적 이름이다. 8bit PNG를 `Raw`로 두면 뷰포트/익스포트에서 다르게 해석될 수 있으니 `Non-Color`를 쓴다.

### 6.4 머티리얼 구성 자동화

```bash
# 원본 텍스처 세트로 머티리얼 구성 (경로 A/B 공통)
blender --background --factory-startup --python pipeline/blender_import.py -- \
  --model output/chair/model.glb --textures output/chair/textures \
  --ao-mode keep --normal-strength 0.8
```

`--normal-strength`, `--roughness-scale`, `--metallic-scale`은 AI 텍스처가 과장된 경우 유용하다(노멀 0.6~0.8, 러프니스 0.9~1.1에서 시작).

---

## 7. 스무스 셰이딩과 노멀

- **Blender 4.1+**: `Mesh.use_auto_smooth`/`auto_smooth_angle`이 제거되고 **Smooth by Angle**(지오메트리 노드 모디파이어)로 대체됐다. 파이썬에서는 `bpy.ops.object.shade_auto_smooth(angle=...)` 또는 `mesh.set_sharp_from_angle(angle=...)`.
- **백그라운드 실행 주의**: `shade_auto_smooth`는 에셋 라이브러리가 없는 `--factory-startup` 환경에서 `CANCELLED`를 반환하고 아무것도 붙이지 않을 수 있다. 스크립트는 `set_sharp_from_angle`을 우선 사용한다.
- **3.x~4.0**: `mesh.use_auto_smooth = True; mesh.auto_smooth_angle = radians(30)`.
- 각도 기준: 유기체 30~60°, 하드서피스 20~40°. 너무 낮으면 면이 보이고, 너무 높으면 날카로운 모서리가 뭉개진다.
- AI 메시는 노멀이 이미 커스텀으로 들어오는 경우가 많다. 스무스 셰이딩이 이상하면 **Clear Custom Split Normals** 후 재계산한다.

---

## 8. 게임 엔진으로 익스포트

### 8.1 FBX (UE5/Unity 공통)

| 설정 | 값 | 이유 |
| --- | --- | --- |
| Selected Objects | On | 케이지/하이폴리 제외 |
| Object Types | Mesh (리깅 시 Armature 추가) | |
| Scale | 1.0, Apply Unit Scale On | 엔진 스케일 1 유지 |
| Apply Scalings | FBX All (또는 프로젝트 규칙) | |
| Forward / Up | -Z / Y | UE5·Unity 공통 |
| Apply Transform | Off | 회전/스케일은 미리 적용 |
| Mesh → Smoothing | Face | 커스텀 노멀/스무스 그룹 |
| Tangents | On (스키닝) | 노멀맵에 필요 |
| Triangulate | On (또는 엔진에서) | |
| Add Leaf Bones | Off | 불필요 본 제거 |
| Path Mode | Copy, Embed Media Off | 텍스처는 별도 관리 |

### 8.2 glTF

| 설정 | 값 |
| --- | --- |
| Format | GLB (단일 파일) 또는 glTF+bin |
| +Y Up | On |
| Apply Modifiers | On |
| Normals / Texcoords | On |
| Materials | Export |
| Images | Auto (PNG 유지) |

### 8.3 UE5 임포트 후

- **노멀 Green 채널**: 블렌더/glTF는 +Y(OpenGL), UE5는 -Y(DirectX). 텍스처 Details에서 `Flip Green Channel`을 켠다(`pipeline/ue5_import.py` 기본값).
- **텍스처 압축**: BaseColor = Default(sRGB), Normal = Normalmap, ORM/마스크 = Masks(Non-sRGB).
- **Nanite**: 로우폴리 캐릭터에는 끈다. 정적 프랍(경로 A)만 켠다.
- **스켈레탈 메시**: 본 수/웨이트 확인, `Import Morph Targets` 필요 여부, 물리 애셋 생성.
- **LOD**: UE5의 LOD 자동 생성보다, 블렌더에서 LOD0/1/2를 만들어 각각 베이킹하는 편이 품질이 좋다.

### 8.4 Unity

- FBX 임포트 → Rig 탭에서 Animation Type(Humanoid/Generic), 머티리얼은 URP/HDRP 셰이더로 재구성.
- 노멀맵은 `Texture Type: Normal map`, `Create from Grayscale` Off.
- AO는 별도 텍스처로 두고 셰이더의 Occlusion 슬롯에 연결(URP Lit은 `_OcclusionMap`).

---

## 9. 자동화 스크립트 사용법

`pipeline/blender_import.py`는 **블렌더 안에서** 실행한다(일반 파이썬 아님). bpy가 없는 환경에서도 import할 수 있게 되어 있어, 순수 함수(텍스처 슬롯 해석, 채널 계획, ratio 계산)는 `tests/test_pipeline.py`에서 검증한다.

### 9.1 경로 A — Nanite 정적 프랍

```bash
blender --background --factory-startup --python pipeline/blender_import.py -- \
  --model output/chair/model.glb \
  --textures output/chair/textures \
  --scale-target 1.0 --origin bottom \
  --export-glb output/chair/chair_game.glb \
  --blend output/chair/chair.blend
```

### 9.2 경로 B — 캐릭터/모바일 (핵심)

```bash
blender --background --factory-startup --python pipeline/blender_import.py -- \
  --model output/hero/model.glb \
  --target-tris 30000 \
  --decimate-symmetry \
  --bake normal,ao,roughness,basecolor \
  --bake-size 2048 --bake-samples 64 \
  --export-fbx output/hero/hero_low.fbx \
  --blend output/hero/hero.blend
```

### 9.3 GUI에서 실행

Scripting 탭 → `pipeline/blender_import.py` 열기 → 상단 `SETTINGS`의 `model`, `target_tris`, `bake` 등을 채우고 Run Script. 같은 파일에 CLI 진입점이 있어, 인자 없이 실행하면 `SETTINGS`를 쓴다.

### 9.4 주요 옵션

| 옵션 | 기본 | 설명 |
| --- | --- | --- |
| `--model` | (필수) | GLB/glTF/FBX |
| `--textures` | `<모델폴더>/textures` | 원본 PBR 텍스처 폴더 |
| `--name` | 파일명 | 에셋 기본 이름(`<name>_High`, `<name>_Low`) |
| `--scale-target` | 0(끔) | 최대 치수를 m 단위로 정규화 |
| `--origin` | none | `bottom`(발바닥 중앙), `center` |
| `--merge-distance` | 0.0001 | 중복 버텍스 병합 |
| `--recalc-normals` | off | 노멀 재계산 |
| `--smooth-angle` | 30 | 스무스 각도(도). -1이면 플랫 |
| `--target-tris` | 0 | **경로 B 핵심.** 목표 삼각형 수 |
| `--decimate` | 0 | 비율 직접 지정(0~1) |
| `--decimate-mode` | collapse | `collapse`/`unsubdiv`/`dissolve` |
| `--decimate-symmetry` | off | 좌우 대칭 유지(`--symmetry-axis X`) |
| `--voxel-size` | 0 | Voxel Remesh 크기(먼저 정리할 때) |
| `--quadriflow-faces` | 0 | Quadriflow 목표 면 수(쿼드 흐름) |
| `--unwrap` | auto | `auto`/`smart`/`keep` |
| `--bake` | (빈 값) | `normal,ao,roughness,basecolor,metallic` |
| `--bake-size` | 2048 | 텍스처 해상도 |
| `--bake-samples` | 32 | AO는 64~256 권장 |
| `--bake-margin` | 8 | UV 경계 여유(px) |
| `--cage-extrusion` | 0(1%) | 케이지 두께 |
| `--bake-gpu` | off | Cycles GPU(OptiX) |
| `--ao-mode` | multiply | `multiply`/`keep`/`ignore` |
| `--normal-strength` | 1.0 | 노멀맵 강도 |
| `--roughness-scale` | 1.0 | 러프니스 배율 |
| `--metallic-scale` | 1.0 | 메탈릭 배율 |
| `--export-fbx` / `--export-glb` | — | 경로 B에서는 로우폴리만 내보냄 |
| `--blend` | — | `.blend` 저장(텍스처 pack) |
| `--drop-high` | off | 베이킹 후 하이폴리 삭제 |
| `--clear-scene` | off | 실행 전 씬 정리 |

### 9.5 리포트

`<모델폴더>/blender_report.json`에 남는다.

```json
{
  "route": "B (캐릭터/모바일 - 리토폴로지 + 폴리곤 감면 + 베이킹)",
  "inspection": [{"triangles": 1204388, "vertices": 1310552, "non_manifold_edges": 0, "uv_layers": ["UVMap"]}],
  "target_tris": 30000,
  "achieved_tris": 29874,
  "bake": {"normal": ".../T_Hero_Low_normal.png", "ao": "...", "roughness": "...", "basecolor": "..."},
  "high": [{"name": "Hero_High", "triangles": 1204388}],
  "low": [{"name": "Hero_Low", "triangles": 29874}],
  "warnings": []
}
```

경고는 조용히 넘어가지 않고 모두 기록된다(예: 텍스처 후보 중복, UV 미생성, 베이크 실패, 목표 삼각형과의 차이).

### 9.6 스크립트의 한계 (먼저 알아둘 것)

- **자동 리토폴로지가 아니다.** Quadriflow/Decimate는 토폴로지 흐름을 "대충" 잡는다. 히어로 캐릭터는 수동 리토폴로지가 필요하다.
- **Smart UV Project는 폴백**이다. 캐릭터 UV는 수동 언랩을 권장한다.
- **여러 머티리얼 슬롯은 하나의 텍스처에 함께 베이크**한다(모든 슬롯에 같은 타깃 이미지를 물린다). 슬롯별 UV 아일랜드가 겹치지 않아야 하며, 슬롯을 나눠 각각의 텍스처를 원하면 수동으로 베이크한다.
- **메탈릭은 EMIT 트릭**이라 하이폴리 머티리얼이 Principled 기반이어야 한다(커스텀 노드 그룹이면 결과가 다를 수 있음).
- **블렌더 버전 차이**로 일부 프로퍼티가 없으면 경고 후 계속 진행한다. 첫 실행 로그를 반드시 확인한다.
- 헤드리스 Cycles 베이킹은 CPU로 돌면 느리다. 2K/캐릭터는 `--bake-gpu`(OptiX) 또는 샘플 수 조절.

---

## 10. 체크리스트

**임포트**

- [ ] 스케일(Dimensions)이 실제 미터와 맞는가
- [ ] 회전/스케일이 적용됐는가(엔진에서 1, 0)
- [ ] 중복 버텍스 병합, 비매니폴드/퇴화 면 확인
- [ ] 노멀 방향, 스무스 셰이딩 확인

**감면/리토폴로지 (경로 B)**

- [ ] 목표 삼각형 수를 예산표에서 정했는가
- [ ] 캐릭터: 관절 엣지 루프, 좌우 대칭 확보
- [ ] Decimate ratio가 목표에 맞는가(리포트 `achieved_tris`)
- [ ] UV 왜곡/찢김 확인

**UV/베이킹**

- [ ] 로우폴리 UV 존재, 아일랜드 겹침 없음
- [ ] 텍셀 밀도 통일(Average Island Scale)
- [ ] 케이지/Extrusion으로 노멀 누출 없음
- [ ] Normal: Tangent, +Y, 보라색 정상
- [ ] AO: 접힌 곳만 어두움
- [ ] Roughness/BaseColor: 하이폴리와 유사
- [ ] Margin 8~16 px, seam 없음
- [ ] 색공간: BaseColor=sRGB, 나머지=Non-Color

**익스포트**

- [ ] 케이지/하이폴리 제외, 로우폴리만 선택
- [ ] FBX/glTF 설정값(8장) 확인
- [ ] UE5 노멀 Green flip, 텍스처 압축 설정
- [ ] 엔진에서 스케일 1, 원점 발바닥, 콜리전/LOD 확인

---

## 11. 문제 해결

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| 노멀맵이 새까맘 | UV 없음, Active 이미지 노드 아님, 선택 순서 오류 | 로우폴리 Active + 하이폴리 선택, Image Texture 노드 Active 확인 |
| 노멀맵이 평평한 보라색 | 하이폴리와 로우폴리가 동일 메시 | 감면본/원본이 별개인지 확인(`Hero_High`/`Hero_Low`) |
| AO가 전체적으로 검음 | Max Ray Distance 과다, 노멀 반전 | 케이지 사용, 노멀 재계산, ray distance 0 |
| 베이크가 몇 초 만에 끝나고 빈 이미지 | 이미지 노드에 이미지 미지정, 렌더 엔진 EEVEE | Cycles 확인, 이미지 지정 |
| seam에 검은 선 | Margin 부족, UV 아일랜드 겹침 | Margin 16, Pack Islands 재실행 |
| 러프니스가 1로 뭉침 | 하이폴리 머티리얼 러프니스 미연결 | 하이폴리 텍스처/값 확인 |
| 감면 후 실루엣이 뭉개짐 | ratio 과다, 대칭 미사용 | `--target-tris` 상향, `--decimate-symmetry`, 보존 Vertex Group |
| 리깅 후 관절이 접히지 않음 | 엣지 루프 부족, Decimate만 적용 | 수동 리토폴로지/Quadriflow, 관절 루프 3개 이상 |
| UV가 찢어짐 | Decimate 전 UV 의존, seam 위치 | 리토폴로지 후 새 UV, seam을 골짜기에 |
| 스무스가 안 먹음 | 4.1+ Auto Smooth 제거, 커스텀 노멀 | `Shade Auto Smooth`/`set_sharp_from_angle`, Clear Custom Normals |
| 블렌더 헤드리스에서 이미지가 분홍색 | 텍스처 경로 깨짐 | `.blend` 저장 시 Pack, 또는 `--textures` 경로 확인 |

---

## 12. 참고 자료

- Blender Manual — Baking: <https://docs.blender.org/manual/en/latest/render/cycles/baking.html>
- Blender 4.1 Release Notes — Auto Smooth 제거: <https://developer.blender.org/docs/release_notes/4.1/modeling/>
- Blender Python API — `bpy.ops.object.bake`, `Mesh.set_sharp_from_angle`: <https://docs.blender.org/api/current/>
- glTF 2.0 Spec — metallicRoughness / occlusion: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html>
- UE5 Nanite 문서: <https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine>
- 이 저장소의 다른 문서: [`pbr_material_pipeline.md`](pbr_material_pipeline.md), [`trellis2_local_setup.md`](trellis2_local_setup.md)
