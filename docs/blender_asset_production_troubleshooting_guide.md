# 블렌더 절차 생성 차량·실내 에셋 트러블슈팅 가이드

> 대상: C++/그래픽스 배경으로 절차 생성 부품(차체·도어·시트·실내)을 직접 만들어 UE5 로 넘기는 개발자
> 범위: **1부** 절차 생성 부품의 LP 저작과 복잡 곡면(차체) → **2부** 베이킹 무결점(겹판·광선 놓침·탄젠트) → **3부** 텍스처 VRAM 예산과 2,000대 인스턴싱 → **4부** 체크리스트·매트릭스
> 기준 시점: **2026-11. Blender 4.2 LTS / 5.x(Cycles 베이크) · Unreal Engine 5.5+ · RTX 3080 10 GiB**
> 함께 쓰는 코드: [`pipeline/vehicle_asset_optimizer.py`](../pipeline/vehicle_asset_optimizer.py) · [`tests/test_vehicle_asset_optimizer.py`](../tests/test_vehicle_asset_optimizer.py)
> 함께 읽는 문서: [블렌더 가공 파이프라인](blender_pipeline.md)(감면 의사결정·UV·케이지) · [PBR 머티리얼 파이프라인](pbr_material_pipeline.md)(ORM·색공간) · [오픈월드 콘텐츠 매뉴얼](open_world_content_and_architecture_guide.md)(탈것·Chaos Vehicles)

---

## 목차

**0. 한눈에: 세 함정은 모두 "경계"에서 터진다**

**1부 — 절차 생성 부품의 LP 저작**

1. [왜 절차 생성 부품은 묶음마다 LP 모드를 새로 짜야 하는가](#1-왜-절차-생성-부품은-묶음마다-lp-모드를-새로-짜야-하는가)
2. [`IsLowPoly` 스위치 아키텍처](#2-islowpoly-스위치-아키텍처)
3. [복잡 곡면(차체) LP: 세 가지 방법의 선택 기준](#3-복잡-곡면차체-lp-세-가지-방법의-선택-기준)
4. [HP 밀착: Shrinkwrap과 버텍스 그룹](#4-hp-밀착-shrinkwrap과-버텍스-그룹)
5. [Custom Split Normals 전송: LP 음영 왜곡 제거](#5-custom-split-normals-전송-lp-음영-왜곡-제거)
6. [부품 클러스터 분할 표준](#6-부품-클러스터-분할-표준)
7. [LP 저작 자동 검증 게이트](#7-lp-저작-자동-검증-게이트)

**2부 — 베이킹 무결점**

8. [베이킹 실패는 세 갈래로 수렴한다](#8-베이킹-실패는-세-갈래로-수렴한다)
9. [겹판: 밀착 부품과 익스플로전 베이킹](#9-겹판-밀착-부품과-익스플로전-베이킹)
10. [광선 놓침: 케이지 표준과 오목·얇은 모서리](#10-광선-놓침-케이지-표준과-오목얇은-모서리)
11. [탄젠트 어긋남과 익스포트 3c 규칙](#11-탄젠트-어긋남과-익스포트-3c-규칙)

**3부 — 텍스처 VRAM 예산과 2,000대 인스턴싱**

12. [계산 규칙: MiB, 밉 체인, 블록 4×4](#12-계산-규칙-mib-밉-체인-블록-44)
13. [차종 18개의 텍스처 상주량 실측 계산](#13-차종-18개의-텍스처-상주량-실측-계산)
14. [ORM 채널 패킹: 3장을 1장으로](#14-orm-채널-패킹-3장을-1장으로)
15. [2,000대 인스턴싱의 메모리와 드로우콜](#15-2000대-인스턴싱의-메모리와-드로우콜)
16. [가상 텍스처링과 밉 스트리밍 풀](#16-가상-텍스처링과-밉-스트리밍-풀)
17. [실내 2048을 1024로: 디테일 노멀 타일 전략](#17-실내-2048을-1024로-디테일-노멀-타일-전략)
18. [RTX 3080 10 GiB 예산표](#18-rtx-3080-10-gib-예산표)
19. [계산기 사용법](#19-계산기-사용법)

**4부 — 체크리스트와 매트릭스**

20. [블렌더 12단계 익스포트·베이크 체크리스트](#20-블렌더-12단계-익스포트베이크-체크리스트)
21. [트러블슈팅 매트릭스](#21-트러블슈팅-매트릭스)
22. [엔진 임포트 필수 세팅](#22-엔진-임포트-필수-세팅)
23. [참고 자료](#23-참고-자료)

---

## 0. 한눈에: 세 함정은 모두 "경계"에서 터진다

이 문서에 정리한 세 문제는 서로 무관해 보이지만 원인이 같다. **모두 "두 표면이 만나는 경계" 또는 "두 단계가 만나는 경계"에서 터진다.**

| 함정 | 터지는 경계 | 증상이 보이는 시점 | 되돌리는 비용 |
| --- | --- | --- | --- |
| LP 저작 | 실루엣·패널 라인 경계 | 엔진에서 차를 10 m 밖에서 볼 때 | 그 부품만 다시 (1~2시간) |
| 굽기 품질 | LP↔HP 광선 경계, UV 탄젠트 경계 | 엔진에서 조명을 받을 때(베이크 직후엔 안 보임) | 18 차종 × 6 클러스터 재베이크(반나절~하루) |
| 텍스처 메모리 | 예산 경계 | 2,000대 배치 후 프레임 드랍·텍스처 뭉개짐 | 해상도 재작업·재쿡(하루) |

세 함정의 공통 구조는 이렇다.

```
   ① 경계를 정의하지 않는다        실루엣, 케이지 여유, 탄젠트 기준
            │
   ② 눈에 보이지 않는 곳에서      블렌더 뷰포트는 4K 텍스처를 1/4로 보여주고
      조용히 틀어진다              엔진 조명·원거리·풀 초과에서만 드러난다
            │
   ③ 18개 차종에 복제된다          한 번의 실수가 108개 메시에 곱해진다
```

그래서 이 문서의 순서는 **"경계를 수치로 정의하고, 게이트에서 자동 검사한다"** 이다. 손으로 눈대중을 잡는 항목(LP 실루엣 오차, 케이지 여유, VRAM 점유율)은 계산기로 옮겼고, 계산기는 `pipeline/vehicle_asset_optimizer.py` 에 있다.

### 0.1 작업 순서를 뒤집으면 비용이 10배가 된다

```
① 클러스터 분할      재질·해상도·LOD 가 바뀌는 곳에서 자른다           (6장)
② LP 생성           IsLowPoly 스위치로 생성 단계에서 감축한다          (2장)
③ 실루엣 보호       차체만 별도 방법(Decimate/Quad/VDB)으로 처리       (3장)
④ 노멀 전송 + 밀착  Shrinkwrap → Data Transfer 커스텀 노멀             (4~5장)
⑤ 겹판 분리         익스플로전 → 케이지 → 베이크 → 복원                (9~10장)
⑥ 삼각화 + 3c       Triangulate 후 Color/노멀/탄젠트 재계산을 건너뛴다 (11장)
⑦ 예산 검증         VRAM·풀·드로우콜을 수치로 확인                     (12~18장)
```

④와 ⑤를 뒤집으면(베이크를 먼저 하고 나중에 노멀을 전송하면) 탄젠트 베이스가 바뀌어 노멀맵이 기울고, ⑥을 건너뛰면 5시간 베이크가 대각선 이음으로 끝난다. **베이크는 가장 비싼 단계이므로 항상 마지막에서 두 번째에 둔다.**

---

## 1. 왜 절차 생성 부품은 묶음마다 LP 모드를 새로 짜야 하는가

절차 생성(Geometry Nodes / Python)으로 차량을 만들면 HP 는 공짜에 가깝게 나온다. 문제는 LP 다. 손으로 만드는 모델러는 "이 형태를 어떻게 단순화할까"를 한 번 판단하고 끝내지만, 절차 생성은 **형태를 만드는 코드와 단순화하는 판단이 분리되어 있지 않다.** 그래서 묶음(클러스터)마다 LP 전용 모드를 새로 짜게 된다.

원인은 세 가지다.

1. **생성 방식이 클러스터마다 다르다.** 차체 상판은 커브 스윕, 펜더는 서피스 패치, 그릴은 불리언+베벨, 실내 버튼은 인스턴스 산포다. 감축해야 할 파라미터가 세그먼트 수인지, 불리언 해상도인지, 인스턴스 수인지가 매번 다르다.
2. **LP 는 "더 적은 폴리곤"이 아니라 "다른 토폴로지"다.** HP 의 세그먼트를 1/4 로 줄이면 실루엣이 각지고, UV 가 늘어나고, 패널 라인이 사라진다. LP 는 실루엣·패널 라인·하드 엣지를 보존하면서 면을 버려야 한다.
3. **결과를 비교할 기준이 없다.** HP 와 LP 를 나란히 놓고 "이 정도면 된다"를 판단하는 대신, 삼각형 수만 보고 통과시키면 엔진에서 실루엣이 무너진다.

해결의 방향은 **"클러스터마다 새로 짜지 않고, 하나의 계약(contract)을 모든 클러스터가 지키게 하는 것"** 이다.

### 1.1 생성 방식 4유형과 LP 전략

| 생성 유형 | 예 | HP 파라미터 | LP 전략 | 주의 |
| --- | --- | --- | --- | --- |
| 커브 스윕 | 차체 상판·루프 레일·범퍼 모서리 | 프로파일 포인트 수, 베벨 단수 | 프로파일 세그먼트 감축 + 베벨 2단 | 실루엣 오차가 각도 오차로 누적된다 |
| 서피스 패치 | 펜더·후드·도어 스킨 | 서브디비전 레벨 | 패치 경계는 유지, 내부만 감축 | 패널 라인(경계)을 자르면 노멀맵으로 복구 불가 |
| 불리언·베벨 | 그릴·에어 인테이크·램프 하우징 | 불리언 해상도, 베벨 폭 | 불리언 결과를 Planar Decimate | 얇은 살(1~2 mm)이 사라지면 구멍이 뚫린다 |
| 인스턴스 산포 | 실내 버튼·에어벤트·리벳 | 인스턴스 밀도 | 거리 LOD 로 밀도만 낮춘다 | LP 모드에서 인스턴스를 지우면 실루엣이 변한다 |

이 네 유형을 하나의 스위치로 묶는 것이 2장의 `IsLowPoly` 아키텍처다.

---

## 2. `IsLowPoly` 스위치 아키텍처

핵심 발상은 단순하다. **HP 생성기와 LP 생성기를 따로 두지 않고, 하나의 그래프에 불리언 입력 하나를 넣고 그 뒤의 모든 파라미터를 분기시킨다.** 그러면 "묶음마다 LP 모드를 새로 짠다"가 "묶음마다 스위치에 어떤 파라미터를 연결할지 정한다"로 바뀐다. 후자는 표로 관리할 수 있다.

### 2.1 노드 그래프 골격

```
                     ┌──────────────── IsLowPoly (Boolean, modifier input) ───────────────┐
                     │                                                                    │
   [Profile Curve]   ▼                                                                    │
        │      ┌─────────────┐   false   ┌──────────────────────────────┐                 │
        ├─────▶│ Switch      │──────────▶│ Resample Curve (Count 64)    │──┐              │
        │      │ (Count)     │           └──────────────────────────────┘  │              │
        │      │             │   true    ┌──────────────────────────────┐  │              │
        │      └─────────────┘──────────▶│ Resample Curve (Count 16)    │──┤              │
        │                               └──────────────────────────────┘  ▼              │
        │                                                        ┌──────────────────┐     │
        └───────────────────────────────────────────────────────▶│ Curve to Mesh    │     │
                                                                 │  (Bevel Depth)   │     │
                                                                 └────────┬─────────┘     │
                                                                          │               │
                          false ┌──────────────────────────────┐          │               │
                    ┌──────────▶│ Bevel (Segments 8)           │◀─────────┘               │
   [Bevel Segments]─┤           └──────────────────────────────┘                          │
                    │  true     ┌──────────────────────────────┐                          │
                    └──────────▶│ Bevel (Segments 2)           │──────────────────────────┘
                                └──────────────────────────────┘
                                          │
                                          ▼
                             [Set Shade Smooth / Store Named Attribute]
```

블렌더의 Geometry Nodes `Switch` 노드는 소켓 타입을 고를 수 있으므로(지오메트리·정수·실수·벡터), 위처럼 **파라미터 값 자체를 분기**할 수 있다. 지오메트리 전체를 두 번 생성해 스위치로 고르는 방식(무거운 쪽)보다, 파라미터만 분기하는 쪽(가벼운 쪽)이 유지보수에 유리하다.

**규칙 하나만 지키면 그래프가 무너지지 않는다: 스위치 이후에 새로운 형태 생성 노드를 추가하지 않는다.** 스위치 뒤에 불리언이나 리메시를 붙이면 LP/HP 의 위상이 다시 갈라져, 4~5장의 노멀 전송·Shrinkwrap 이 매칭되지 않는다.

### 2.2 곡선 프로파일 세그먼트 감축: 오차로 결정한다

세그먼트 수를 "느낌"으로 정하면 클러스터마다 기준이 달라진다. 기준은 **실루엣 오차(mm)** 다. 반지름 `R` 인 원호를 `n` 등분할 때 생기는 최대 처짐(sagitta)은

```
sagitta = R · (1 - cos(π / n))
```

| R (mm) | n=12 | n=16 | n=24 | n=32 | n=48 | n=64 |
| --- | --- | --- | --- | --- | --- | --- |
| 300 | 10.2 mm | 5.8 mm | 2.6 mm | 1.4 mm | 0.6 mm | 0.4 mm |
| 500 | 17.0 mm | 9.6 mm | 4.3 mm | 2.4 mm | 1.1 mm | 0.6 mm |
| 800 | 27.3 mm | 15.4 mm | 6.8 mm | 3.9 mm | 1.7 mm | 1.0 mm |

목표 오차를 정하는 근거는 화면이다. UE 기본 수평 FOV 90°, 1920 px, 관찰 거리 10 m 라면 화면 폭은 약 20 m 이고 **1 px ≈ 10.4 mm** 다.

- 10 m 거리에서 티가 나지 않으려면 오차 ≤ 10 mm → R=500 에서 n ≥ 16.
- 근접(3 m)에서도 버티려면 1 px ≈ 3.1 mm → 오차 ≤ 3 mm → n ≥ 24~32.
- 그래서 **차체 상판·펜더의 LP 프로파일은 n=24~32**, 작은 부품(램프 링 R=120)은 n=12~16 이면 충분하다.

이 계산을 클러스터 표(2.5)에 숫자로 적어 두면, 새 부품을 추가할 때 같은 판단을 반복하지 않는다.

### 2.3 베벨 단계 축소: 라운드는 노멀맵에 맡긴다

판금 패널의 모서리는 실제로 R2~R4 mm 의 미세 라운드가 있다. HP 에서는 이 라운드가 하이라이트를 만들어내지만, **LP 에서 이 라운드를 유지하면 삼각형이 라운드에 전부 소모된다.**

| 엣지 유형 | HP 처리 | LP 처리 | 근거 |
| --- | --- | --- | --- |
| 패널 라인(도어 이음) | Bevel 2단 + 샤프 마크 | **기하로 유지** (베벨 1단 또는 샤프 엣지) | 패널 라인은 노멀맵으로 복구되지 않는다(UV 경계·실루엣) |
| 판금 곡면 모서리 | Bevel 8~12단 | 베벨 2단 | 라운드의 하이라이트는 노멀맵이 만든다 |
| 볼트·리벳 헤드 | 서브디비전 | 실루엣만(육각 프리즘) | 3 m 밖에서 구분 불가 |
| 창틀·몰딩 홈 | 불리언 + 베벨 | 홈 폭 유지, 깊이만 축소 | 홈이 사라지면 AO·노멀 모두에서 사라진다 |

즉 LP 의 베벨은 **"각도는 남기고 곡률은 버린다"**. 남길 것(패널 라인, 홈 폭)과 버릴 것(곡률)을 구분하는 것이 전부다.

### 2.4 파이썬 쪽 스위치: 모디파이어 입력을 직접 만진다

블렌더 4.x/5.x 에서 Geometry Nodes 모디파이어의 입력은 `modifier[identifier]` 로 접근한다. 클러스터를 일괄로 LP/HP 두 벌 만들 때 쓰는 함수다.

```python
import bpy

def set_lowpoly(obj: bpy.types.Object, low: bool, socket_name: str = "IsLowPoly") -> bool:
    """노드 그룹 모디파이어의 IsLowPoly 입력을 low 로 맞춘다."""
    touched = False
    for mod in obj.modifiers:
        if mod.type != "NODES" or not mod.node_group:
            continue
        for item in mod.node_group.interface.items_tree:
            if getattr(item, "in_out", None) != "INPUT":
                continue
            if item.name != socket_name:
                continue
            mod[item.identifier] = low
            touched = True
    return touched


def build_pair(cluster: bpy.types.Object) -> tuple[bpy.types.Object, bpy.types.Object]:
    """한 클러스터에서 High/Low 두 벌을 만든다(원본은 High 로 남긴다)."""
    high = cluster
    high.name = f"{cluster.name}_High"
    set_lowpoly(high, False)

    low = cluster.copy()
    low.data = cluster.data.copy()
    low.name = f"{cluster.name}_Low"
    bpy.context.collection.objects.link(low)
    set_lowpoly(low, True)
    return high, low
```

주의할 점 두 가지.

- **적용(Apply)하지 않는다.** LP 를 Apply 하면 `IsLowPoly` 를 다시 뒤집을 수 없어 파라미터를 고칠 때마다 처음부터 다시 만들어야 한다. Bake·Export 전에만 일시적으로 평가되게 두고, 엔진으로 내보낼 때만 Evaluate 된 메시를 쓴다.
- **LP 쪽에는 조용한 실패가 있다.** 소켓 이름이 바뀌면 위 함수가 `False` 를 돌려주고 LP 는 HP 그대로 남는다. 그래서 함수가 `touched` 를 반환하게 하고, 배치 스크립트가 이 값을 확인해 실패를 즉시 멈춘다(7장 게이트).

### 2.5 클러스터별 LP 생성 모드 표준화: 매니페스트

클러스터마다 다른 판단을 산출물로 고정한다. 이 표(JSON)가 없으면 6개월 뒤 같은 고민을 다시 한다.

| 필드 | 예 | 의미 |
| --- | --- | --- |
| `cluster` | `body_shell` | 6장의 클러스터 이름 |
| `generator` | `GN/Body_Sweep` | 사용한 노드 그룹(또는 `py/seat.py`) |
| `lowpoly_switch` | `IsLowPoly` | 스위치 소켓 이름 |
| `profile_segments` | `hp 64 / lp 28` | 2.2 식으로 역산한 값 |
| `bevel_segments` | `hp 8 / lp 2` | 2.3 표 기준 |
| `tri_budget` | `12000` | LP 삼각형 상한 |
| `silhouette_tol_mm` | `3.0` | 허용 실루엣 오차 |
| `uv_sets` | `1` | 라이트맵 없음(동적 차량) |
| `bake_res` | `4096` | 노멀/AO/ORM 해상도 |
| `method` | `decimate_planar` | 3장의 LP 방법 |

```json
{
  "cluster": "body_shell",
  "generator": "GN/Body_Sweep",
  "lowpoly_switch": "IsLowPoly",
  "profile_segments": {"hp": 64, "lp": 28},
  "bevel_segments": {"hp": 8, "lp": 2},
  "tri_budget": 12000,
  "silhouette_tol_mm": 3.0,
  "uv_sets": 1,
  "bake_res": 4096,
  "method": "decimate_planar"
}
```

이 매니페스트를 읽어 검증하는 것이 7장 게이트이고, 4부의 체크리스트가 이 순서를 그대로 따른다.

---

## 3. 복잡 곡면(차체) LP: 세 가지 방법의 선택 기준

차체·펜더·후드처럼 곡률이 두 방향으로 겹치는 면은 `IsLowPoly` 세그먼트 감축만으로는 안 된다. 감축한 프로파일이 서로 교차하거나, 패널 라인이 곡면 위에서 흐르면서 방향이 틀어진다. 여기서는 별도 리토폴로지 방법을 쓴다.

### 3.1 세 후보 비교

| 기준 | Edge-Angle Decimate | Quad Remesher / QuadriFlow | VDB(Voxel) Remesh + Shrinkwrap |
| --- | --- | --- | --- |
| 실루엣 보존 | 각도 한계에 따라 **붕괴 가능** | 가이드 커브가 있으면 좋음 | 원본 형상을 거의 그대로 유지 |
| 패널 라인 보존 | `Delimit` 로 UV/Sharp 를 지키면 양호 | **파괴**(재언랩 필요) | **파괴** |
| UV 보존 | **보존**(늘어남은 있음) | 파괴 → 재언랩 | 파괴 → 재언랩 |
| 토폴로지 품질 | 삼각형, 흐름 없음 | 사각형 흐름(쿼드) | 균일하지만 흐름 없음 |
| 속도 | 수 초 | 수 분~수십 분 | 수십 초~수 분 |
| 결정성 | 높음(파라미터 고정) | 낮음(시드·버전 의존) | 중간 |
| 잘 맞는 부품 | 상판·도어 스킨처럼 평평한 판 | 히어로 차체, 노출 클로즈업 | 시트·대시보드·유기적 형태, 1차 정리 |

**결론부터: 세 방법은 경쟁 관계가 아니라 순서다.**

```
  HP(절차 생성, 수십만~수백만 삼각형)
        │
        ├─(평평한 판)──────────────▶ ④ Decimate(Planar) → 끝
        │
        └─(복잡 곡면)──▶ ① VDB Remesh(균일화) ─▶ ② Decimate(Planar) ─▶ ③ Shrinkwrap
                                                          │
                                        (클로즈업 히어로만) └─▶ QuadriFlow ─▶ 재언랩
```

차체는 ①→②→③ 이 표준이고, 노출이 많은 히어로 1~2 차종만 ② 뒤에 QuadriFlow 를 끼운다. Quad 리토폴로지를 18 차종 전체에 돌리면 시간이 폭발하고, 결정성이 낮아 재현이 안 된다.

### 3.2 실루엣 보호: 3면 실루엣 오차를 측정한다

실루엣은 **정면·측면·후면 세 방향의 실루엣 마스크**로 측정한다. 방법은 간단하다.

1. 오쏘 카메라 3대(±X, ±Y, ±Z 중 차량 기준 정면/측면/상면)로 HP 와 LP 를 각각 렌더해 **알파 마스크**만 저장한다.
2. 두 마스크를 XOR 하면 "HP 에는 있는데 LP 에는 없는 영역"이 남는다.
3. 그 영역의 **최대 폭(mm)** 과 **면적 비율(%)** 을 기록한다.

기준은 이렇게 잡는다.

| 부품 | 실루엣 최대 오차 | 면적 오차 | 판정 |
| --- | --- | --- | --- |
| 차체 상판·루프 | ≤ 2 mm | ≤ 0.5% | 근접 관찰 가능 |
| 펜더·도어 스킨 | ≤ 3 mm | ≤ 0.8% | 표준 |
| 범퍼·스커트 | ≤ 5 mm | ≤ 1.5% | 원거리 위주 |
| 실내 트림 | ≤ 2 mm | ≤ 2% | 시야가 좁아 오차가 커도 된다 |

**패널 라인은 실루엣보다 우선한다.** 이유는 복구 가능성이다. 실루엣이 2 mm 밀린 것은 카메라 거리와 각도에서 흡수되지만, 패널 라인이 사라지거나 3 cm 옆으로 밀리면 노멀맵으로 되돌릴 수 없다(패널 라인은 하드 엣지와 UV 경계를 동반한다). 그래서 리토폴로지 후 **패널 라인 위치 오차를 먼저 확인하고, 그 다음 실루엣을 본다.**

### 3.3 Decimate 세팅: Planar 를 기본으로, Collapse 는 예산 확정용

블렌더 `Decimate` 모디파이어는 세 모드가 있고, 차체에서 쓰는 것은 두 개다.

| 모드 | 파라미터 | 쓰는 곳 | 주의 |
| --- | --- | --- | --- |
| Planar(평면 붕괴) | `Angle Limit` 1~3°, `Delimit` = UV/Sharp/Seam | 곡률이 완만한 판, VDB 정리 후 | 각도 한계가 크면 곡면이 평면으로 붕괴 |
| Collapse(비율) | `Ratio` = 목표/현재, `Triangulate` on | 목표 삼각형 수를 정확히 맞출 때 | UV 는 보존되지만 seam 너머로 붕괴하면 텍스처가 늘어난다 |
| Un-Subdivide | 반복 횟수 | 서브디비전으로 만든 격자 | 곡선 스윕 결과에는 거의 무의미 |

실무 순서는 **Planar 로 한 번(불필요한 평면 제거) → Collapse 로 예산 맞춤** 이다.

```python
import bpy, math

def decimate_to_budget(obj: bpy.types.Object, target_tris: int, angle_deg: float = 2.0) -> None:
    mesh = obj.data
    planar = obj.modifiers.new("LP_Planar", "DECIMATE")
    planar.decimate_type = "DISSOLVE"
    planar.angle_limit = math.radians(angle_deg)
    planar.delimit = {"UV", "SEAM", "SHARP"}
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=planar.name)

    current = sum(len(p.vertices) - 2 for p in mesh.polygons)
    if current <= target_tris:
        return
    collapse = obj.modifiers.new("LP_Collapse", "DECIMATE")
    collapse.decimate_type = "COLLAPSE"
    collapse.ratio = target_tris / max(current, 1)
    collapse.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=collapse.name)
```

`use_collapse_triangulate`(삼각화)를 켜는 이유는 결과를 **예측 가능**하게 만들기 위해서다. 끄면 사각형이 남고, 이후 삼각화 방향에 따라 노멀맵 결과가 달라진다(11.2).

### 3.4 QuadriFlow: 히어로 차체에만, 60~70% 예산으로

`QuadriFlow Remesh` 는 사각형 흐름을 만들지만 UV 를 파괴한다. 그래서 **재언랩 비용을 항상 함께 계산**해야 한다.

| 파라미터 | 권장 | 이유 |
| --- | --- | --- |
| `target faces` | 삼각형 예산의 60~70% | 리메시 후 남은 삼각형·경계 보정 여유 |
| `preserve sharp` | ON | 패널 라인 유지 |
| `preserve mesh boundary` | ON | UV 섬 경계·개구부 유지 |
| `smooth normals` | OFF | 노멀은 5장에서 HP 로부터 받는다 |
| `use mesh symmetry` | 차체만 ON | 좌우 대칭이 무너지면 대칭 UV 재사용이 깨진다 |

재언랩은 **패널 단위로** 한다. 차체 전체를 하나의 UV 섬으로 펴면 4096 에서 텍셀 밀도가 1 px/mm 아래로 떨어져 도어 손잡이 주변이 뭉개진다. 6장의 클러스터·패널 단위로 나눠 펴고, 패딩은 4096 에서 8 px, 2048 에서 4 px 를 둔다.

### 3.5 VDB Remesh + Shrinkwrap: 복잡 곡면의 기본 경로

`Remesh` 모디파이어의 Voxel 모드는 OpenVDB 기반으로, **표면을 균일한 밀도로 다시 만든다.** 절차 생성 HP 는 커브 밀도가 구간마다 달라 삼각형이 몰려 있는데, VDB 는 이 불균일을 지운다. 그 다음 Decimate 로 예산을 맞추고 Shrinkwrap 으로 HP 표면에 붙인다(4장).

복셀 크기는 **보존해야 할 최소 특징의 1/2~1/3** 로 잡는다.

| 보존 대상 | 최소 특징 | 복셀 크기 | 4.6 m × 1.9 m 차체 표면적 12 m² 기준 삼각형(≈ 2A/h²) |
| --- | --- | --- | --- |
| 패널 라인 홈 폭 4 mm | 4 mm | 1.5~2 mm | 약 600만~1,000만 |
| 몰딩 폭 8 mm | 8 mm | 3~4 mm | 약 150만~270만 |
| 실루엣만(원거리 LOD) | 20 mm | 8~10 mm | 약 24만~38만 |

표에서 보듯 **VDB 를 최소 특징 기준으로 돌리면 삼각형이 수백만 개** 나온다. VDB 는 LP 를 만드는 도구가 아니라 **"균일한 중간 메시"를 만드는 도구**이고, LP 는 그 다음 Decimate 가 만든다. 이 순서를 뒤집으면(VDB 를 LP 위에 돌리면) 패널 라인이 사라지고 원래 LP 보다 무거워진다.

주의할 점 하나. VDB 는 얇은 판(도어 스킨 두께 1 mm, 유리 3 mm)을 **닫힌 덩어리로 만든다.** 차체 스킨처럼 열린 서피스는 VDB 후에 안쪽이 메워져 노멀 방향이 뒤집힐 수 있으므로, VDB 는 **닫힌 부품**(시트, 대시보드, 램프 하우징)에만 쓰고 열린 서피스는 3.3 의 Decimate 경로를 쓴다.

---

## 4. HP 밀착: Shrinkwrap과 버텍스 그룹

Decimate 로 예산을 맞춘 LP 는 HP 표면에서 수 mm~수십 mm 떠 있다. 이 상태로 베이크하면 노멀맵이 "떨어진 거리"를 기록해 하이라이트가 뭉개지고, 실루엣 안쪽에 틈이 보인다. Shrinkwrap 은 LP 를 HP 표면에 붙이는 단계다.

### 4.1 자동 Shrinkwrap 이 차체에서 실패하는 이유

`Nearest Surface Point` 로 전체를 붙이면 세 가지가 깨진다.

1. **패널 라인 근처에서 옆 패널로 빨려간다.** 도어와 펜더 사이 4 mm 틈에서 LP 버텍스가 펜더 안쪽 면에 붙어, 도어 LP 가 펜더를 향해 휘어진다.
2. **실루엣이 파도처럼 흔들린다.** LP 버텍스가 HP 표면의 요철을 그대로 따라가면서, 원래 직선이던 실루엣이 물결이 된다.
3. **뒤집힌 면이 생긴다.** 오목한 홈 안쪽의 LP 버텍스가 반대편 벽에 붙으면 그 면의 노멀이 뒤집혀 베이크가 검게 나온다.

그래서 Shrinkwrap 은 **클러스터 단위로, 가중치로 제어해서** 건다.

### 4.2 가중치 설계: 경계 0, 내부 1

| 위치 | 가중치 | 이유 |
| --- | --- | --- |
| 패널 라인·UV seam 에서 0~5 mm | 0.0 | 경계는 기하로 유지해야 한다(옆 패널로 빨려가지 않게) |
| 경계에서 5~25 mm | 0.0 → 1.0 (smoothstep) | 급격한 변화는 실루엣 파동을 만든다 |
| 패널 내부 | 1.0 | HP 곡률을 그대로 받는다 |
| 오목 홈 안쪽 | 0.0~0.3 | 반대편 벽으로 붙는 것을 막는다 |
| 얇은 판(두께 < 3 mm)의 뒷면 | 0.0 | 뒷면이 앞면으로 붙으면 판이 사라진다 |

```python
import bmesh, mathutils

def shrinkwrap_weights(obj, boundary_edges, falloff: float = 0.025, name: str = "SW_Weight"):
    """패널 라인/샤프 엣지에서의 거리로 0→1 가중치를 만든다(장면 단위 m)."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.edges.ensure_lookup_table()
    boundary_verts = {v for e in bm.edges if e.index in boundary_edges for v in e.verts}

    vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    for v in bm.verts:
        if not boundary_verts:
            w = 1.0
        else:
            d = min((v.co - b.co).length for b in boundary_verts)
            t = min(d / falloff, 1.0)
            w = t * t * (3.0 - 2.0 * t)          # smoothstep
        vg.add([v.index], w, "REPLACE")
    bm.free()
    return vg
```

버텍스 수가 많은 메시에서는 위의 최소 거리 계산이 O(n·m) 이라 느리다. 실무에서는 `mathutils.kdtree.KDTree` 로 경계 버텍스를 넣고 `find()` 를 쓰면 수 초 안에 끝난다.

### 4.3 Shrinkwrap 세팅표

| 설정 | 값 | 이유 |
| --- | --- | --- |
| Wrap Method | `Nearest Surface Point` | 표준. 축 방향 투영은 곡면에서 실패 |
| Wrap Mode | `On Surface` (`Outside` 는 노멀맵 여유가 필요할 때) | 안쪽/바깥쪽 고정 |
| Offset | `0.0002~0.0005 m` (0.2~0.5 mm) | LP 를 HP 표면에서 살짝 띄워 노멀맵이 "0" 이 아닌 값을 갖게 한다 |
| Target | **클러스터별 HP** (전체 HP 아님) | 옆 부품으로 빨려가는 것을 막는다 |
| Vertex Group | `SW_Weight`, `Factor 1.0` | 4.2 의 가중치 |
| Project(대안) | `Negative/Positive` + 축 지정 | 문처럼 평평한 판에서만. 곡면은 금지 |

`Offset` 을 0 으로 두면 LP 가 HP 와 정확히 겹쳐 노멀맵이 거의 (0.5, 0.5, 1.0) 이 되고, 압축(BC5)에서 미세 곡률이 사라진다. 0.3 mm 정도 띄우는 것이 안전하다.

### 4.4 밀착 후 확인

- **최대 변위**: Shrinkwrap 전/후 버텍스 이동량의 최댓값. 실루엣 허용치(3.2 표)를 넘으면 Decimate 비율을 다시 잡는다.
- **뒤집힌 면**: LP 면 노멀과 HP 최근접 노멀의 내적이 음수인 면의 개수. 1개라도 있으면 그 자리가 검게 구워진다.
- **얇은 판 두께**: 도어 스킨·유리의 앞뒤 버텍스가 같은 위치로 붙었는지(두께 0) 확인.

---

## 5. Custom Split Normals 전송: LP 음영 왜곡 제거

LP 는 면이 각져 있다. 여기에 부드러운 셰이딩을 주면 **없는 곡률을 있는 것처럼 보간**해서, 하이라이트가 흐르고 패널이 부풀어 보인다. 반대로 하드 엣지를 전부 살리면 패널 라인 옆면이 각진 띠로 보인다. 해법은 **HP 의 노멀을 LP 로 옮겨 적는 것**이다. 기하는 각져 있어도 음영은 HP 와 같아진다.

### 5.1 절차 (블렌더 4.1+)

```python
import bpy

def transfer_hp_normals(low: bpy.types.Object, high: bpy.types.Object) -> None:
    mod = low.modifiers.new("HP_Normals", "DATA_TRANSFER")
    mod.object = high
    mod.use_loop_data = True
    mod.data_types_loops = {"CUSTOM_NORMAL"}
    mod.loop_mapping = "POLYINTERP_NEAREST"   # 곡면 경계에서 계단이 없다
    mod.mix_mode = "REPLACE"
    bpy.context.view_layer.objects.active = low
    bpy.ops.object.modifier_apply(modifier=mod.name)
    low.data.update()
```

블렌더 4.1 에서 **Auto Smooth 속성이 제거**되었고, 이후 버전에서는 커스텀 노멀이 있으면 그대로 사용된다. 즉 4.1+ 에서는 별도 토글이 필요 없다(4.0 이하에서는 `mesh.use_auto_smooth = True` 와 각도 설정이 필요했다). 이 차이를 모르고 4.0 용 튜토리얼을 따라 하면 "전송했는데 아무 변화가 없다"가 된다.

### 5.2 흔한 실패 네 가지

| 실패 | 증상 | 원인 | 수정 |
| --- | --- | --- | --- |
| 전송이 무효 | LP 가 그대로 각져 보임 | 모디파이어 순서상 Decimate 뒤에서 적용되어 새 버텍스에 노멀이 없음 | **Decimate 를 모두 Apply 한 뒤** 마지막에 Data Transfer |
| 계단진 하이라이트 | 곡면에 줄무늬 | `loop_mapping = NEAREST_POLYNOR`(면 노멀 근사) | `POLYINTERP_NEAREST` |
| 이중 적용 | 노멀맵 적용 시 곡률이 두 배로 부풀어 보임 | 커스텀 노멀 전송 + HP 오브젝트 공간 노멀 베이킹 | 탄젠트 공간으로 다시 베이크(11장) |
| 엔진에서 기울어짐 | 노멀맵 방향이 한쪽으로 쏠림 | 베이크 후 노멀을 전송해 탄젠트 베이스만 바뀜 | 전송 → 베이크 순서로 고정 |

### 5.3 순서 규칙: 전송 먼저, 베이크 나중

커스텀 노멀은 **탄젠트 베이스 자체를 바꾼다.** 탄젠트는 UV 와 버텍스 노멀에서 계산되므로(11.1), 노멀을 나중에 바꾸면 엔진이 쓰는 탄젠트가 베이크 당시와 달라져 노멀맵이 기운다.

```
  Decimate Apply ─▶ Shrinkwrap ─▶ Data Transfer(커스텀 노멀) ─▶ 베이킹 ─▶ Triangulate(Keep Custom Normals) ─▶ Export
```

이 순서를 한 번만 어기면 18 차종 전체가 "조명이 이상하다"가 되고, 원인을 찾는 데 하루가 걸린다. 그래서 4부 체크리스트의 3번이 이 항목이다.

**A/B 검증**: LOD0 에서 같은 카메라로 (a) 커스텀 노멀 없음, (b) 있고 노멀맵 없음, (c) 있고 노멀맵 있음 세 장을 렌더해 나란히 둔다. (b) 에서 하이라이트가 매끄럽고 (c) 에서 디테일이 더해지면 정상이다. (c) 에서 하이라이트가 부풀면 5.2 의 "이중 적용"이다.

---

## 6. 부품 클러스터 분할 표준

분할은 취향이 아니라 **제약**이다. 재질이 바뀌는 곳, 베이크 해상도가 바뀌는 곳, LOD 전환 단위, 패널 라인 — 이 네 곳에서만 자른다. 잘못 자르면 9장의 겹판과 12장의 예산 초과가 동시에 온다.

### 6.1 6+1 클러스터

| 클러스터 | 포함 | LP 삼각형 | 재질 슬롯 | 베이크 | 특수 규칙 |
| --- | --- | --- | --- | --- | --- |
| `body_shell` | 차체 상판·펜더·범퍼·스커트 | 8,000~15,000 | 페인트 1 | 4096 ×3 | 실루엣 최우선(3.2), 패널 라인 유지 |
| `doors` | 도어·후드·트렁크 리드 | 2,000~4,000 (각) | 페인트 + 내장 1 | 2048 ×3 | 개구부 경계 정합, 경첩 축 기준 |
| `glass_lights` | 유리·램프 커버·리플렉터 | 500~1,500 | 유리 1 + 발광 1 | 1024 ×2 | 유리에는 노멀 베이크 금지(굴절·틴트로 처리) |
| `interior` | 대시보드·콘솔·트림 패널 | 12,000~20,000 | 실내 2~3 | 2048 ×3 | 시야 1~3 m, 17장의 타일 전략 |
| `seats` | 프레임·쿠션·벨트 | 3,000~5,000 (각) | 시트 1~2 | 2048 ×3 | **겹판 최다 발생 지점**(9장) |
| `wheels` | 휠·타이어·브레이크 | 3,000~6,000 | 휠 1 | 2048 ×2 | 4개가 1세트를 공유 → UV 하나, 회전은 엔진 |
| `trim_decal` (+) | 몰딩·엠블럼·번호판 | 300~800 | 데칼 1 | 1024 ×1 | 트림 시트(알파)로 대체 가능 |

합계는 차종당 **35,000~50,000 삼각형**이다. 이 수치는 Nanite 로 넘기면 여유가 크고, 스켈레탈·모바일 경로에서는 상한에 가깝다.

### 6.2 분할 경계 규칙 4가지

1. **패널 라인에서 자른다.** 실제 판금 이음(도어 틈, 후드 라인)이 자연스러운 경계다. 여기서 자르면 UV seam 과 하드 엣지가 일치해 노멀맵 이음이 보이지 않는다.
2. **재질이 바뀌는 곳에서 자른다.** 페인트와 유리는 압축 포맷도, 베이크 해상도도 다르다.
3. **베이크 해상도가 바뀌는 곳에서 자른다.** 4096 과 2048 을 한 UV 세트에 섞으면 2048 부분이 절반 해상도가 된다.
4. **LOD 전환 단위로 자른다.** 실내는 30 m 밖에서 통째로 사라지므로, 외장과 같은 클러스터에 묶으면 LOD 를 못 내린다.

### 6.3 잘못 자른 예와 결과

| 잘못된 분할 | 결과 | 올바른 분할 |
| --- | --- | --- |
| 시트와 시트 프레임을 한 오브젝트로 | 프레임이 쿠션을 뚫고 나와 겹판 광선 간섭(9장) | 프레임/쿠션 분리, 같은 클러스터 안 두 오브젝트 |
| 유리와 램프를 한 UV 에 | 유리 투명도와 발광 마스크가 한 머티리얼에 뒤엉킴 | 재질별 분리 |
| 실내를 외장과 같은 베이크에 | 실내가 4096 을 나눠 쓰거나 2048 로 뭉개짐 | 해상도별 분리 |
| 휠 4개를 각각 UV | 같은 텍스처를 4번 저장 | 1세트 공유, 인스턴스 배치 |

---

## 7. LP 저작 자동 검증 게이트

LP 는 눈으로 "괜찮아 보인다"가 가장 위험한 단계다. 뷰포트는 4K 텍스처를 1/4 로 보여주고, 조명은 HDRI 하나뿐이다. **베이크 전에 자동 검사로 막는다.**

### 7.1 검사 항목과 임계값

| 항목 | 계산 | 임계값 | 실패 시 |
| --- | --- | --- | --- |
| 삼각형 수 | `sum(len(p.vertices) - 2)` | ≤ 매니페스트 `tri_budget` | Decimate 비율 재조정 |
| 커스텀 노멀 존재 | `mesh.has_custom_normals` | True | 5장 재실행(순서 확인) |
| 뒤집힌 면 | 면 노멀·HP 최근접 노멀 내적 < 0 | 0 개 | 해당 면 리토폴로지 |
| UV 겹침 | UV 섬 면적 합 / 0~1 면적 | ≤ 95% (패딩 8 px 기준) | 언랩 재실행 |
| 늘어난 삼각형 | UV 면적/3D 면적 비의 p99 | ≤ 4배 | 패널 단위 재언랩 |
| 실루엣 오차 | 3.2 의 3면 XOR | ≤ 표의 값 | 3장 방법 재선택 |
| 두께 0 판 | 대칭 버텍스 쌍 거리 < 0.1 mm | 0 개 | Solidify 또는 가중치 조정 |
| `_Low` 이름 규칙 | 이름이 `*_Low`/`*_High` | 100% | 배치 중단 |

### 7.2 배치 스크립트의 게이트

```python
def gate_cluster(low, high, manifest, report):
    import bpy
    tris = sum(len(p.vertices) - 2 for p in low.data.polygons)
    if tris > manifest["tri_budget"]:
        report.append((low.name, "FAIL", f"tris {tris} > {manifest['tri_budget']}"))
        return False
    if not low.data.has_custom_normals:
        report.append((low.name, "FAIL", "custom normals missing — 5장 순서 확인"))
        return False
    if not low.name.endswith("_Low") or not high.name.endswith("_High"):
        report.append((low.name, "FAIL", "naming convention"))
        return False
    report.append((low.name, "OK", f"{tris} tris"))
    return True
```

게이트가 `FAIL` 이면 **그 차종의 베이크를 시작하지 않는다.** 108개 메시를 5시간 베이크한 뒤 하나가 실패하면, 재베이크 동안 다른 작업이 전부 밀린다.

---

## 8. 베이킹 실패는 세 갈래로 수렴한다

베이크 결과가 이상할 때 원인은 대개 다음 셋 중 하나다. 증상으로 갈래를 정하고, 해당 장으로 바로 간다.

| 증상 | 원인 갈래 | 확인 | 장 |
| --- | --- | --- | --- |
| 마젠타·검은 점, 구멍 | 광선이 하이폴리를 못 맞음 | 케이지 여유·Ray Distance | 10장 |
| 이웃 부품 무늬가 찍힘, 판이 겹쳐 보임 | 광선이 다른 부품을 먼저 맞음 | 부품 간 거리·겹침 | 9장 |
| 대각선 이음, 하이라이트 회전, 좌우 비대칭 | 탄젠트 베이스 불일치 | 삼각화·노멀 소스·G 채널 | 11장 |
| 전체적으로 밋밋함 | LP 가 HP 에서 떨어져 있음 | Shrinkwrap·오프셋 | 4장 |
| 패널 라인이 흐릿함 | LP 하드 엣지 소실 | 커스텀 노멀·베벨 | 5장 |

**중요한 성질**: 베이크 실패는 **베이크 직후에 보이지 않는다.** 블렌더의 머티리얼 프리뷰는 노멀맵을 강한 조명으로 보여주기 때문에 검은 점이 가려진다. 검증은 **1:1 확대 + 엔진 조명** 두 곳에서 해야 한다.

---

## 9. 겹판: 밀착 부품과 익스플로전 베이킹

겹판(overlapping plates)은 "두 표면이 1 mm 안에서 겹쳐 있는" 상태다. 시트 프레임과 쿠션, 안전벨트와 시트, 몰딩과 패널이 전형이다. 이 상태로 베이크하면 광선이 **먼저 만난 면**을 기준으로 노멀을 기록하므로, LP 면이 기대한 HP 면과 다른 면을 맞아 무늬가 뒤섞인다.

### 9.1 원인 분류

| 유형 | 예 | 광선이 하는 일 | 대응 |
| --- | --- | --- | --- |
| 밀착 부품 | 시트 프레임 ↔ 쿠션, 벨트 ↔ 등받이 | 두 부품 사이 틈에서 서로의 면을 맞음 | **익스플로전(축 분리)** |
| 이중 곡면 | 외피 + 안감, 도어 스킨 + 방음재 | 안감이 외피보다 먼저 맞음 | 안감을 별도 클러스터로 분리 |
| 안쪽 면 | 보이지 않는 뒤판·보강재 | 케이지가 뒤판을 통과 | 뒤판을 베이크 대상에서 제외(별도 Low 없음) |
| 두께 0 판 | 장식 몰딩, 엠블럼 | 앞뒤 면이 같은 위치 → 노멀 상쇄 | Solidify 로 최소 1 mm 부여 |

### 9.2 진단: 광선 히트맵과 교차 검사

베이크 결과에서 **순수 마젠타(1, 0, 1)** 와 **순수 검정** 픽셀 비율을 세면 광선 실패가 수치로 나온다. 블렌더 파이썬으로 이미지 픽셀을 직접 읽을 수 있다.

```python
import bpy

def count_ray_misses(image_name: str, tol: float = 0.02) -> tuple[int, int]:
    """노멀맵에서 마젠타(레이 미스)/검정(0 노멀) 픽셀 수를 센다."""
    img = bpy.data.images[image_name]
    px = list(img.pixels)          # RGBA float, 선형
    miss = black = 0
    for i in range(0, len(px), 4):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if abs(r - 1.0) < tol and g < tol and abs(b - 1.0) < tol:
            miss += 1
        elif r < tol and g < tol and b < tol:
            black += 1
    return miss, black
```

> 주의: 베이크 이미지가 8bit sRGB 로 저장되면 값이 0~1 사이로 매핑되어 판정이 흐려진다. 검증용으로는 **32bit(선형) 이미지에 베이크**하고, 마지막에 8bit BC5 로 내보낸다. 블렌더 이미지의 `.pixels` 는 항상 선형 float 이므로 위 코드는 두 경우 모두 동작하지만, 8bit 저장 시 마젠타가 (1.0, 0.0, 1.0) 에서 약간 벗어날 수 있어 `tol` 을 0.02~0.05 로 둔다.

부품 간 실제 교차는 BVH 로 센다. LP 와 HP 가 서로 뚫고 있는 쌍을 찾으면, 익스플로전 대상 목록이 자동으로 나온다.

```python
from mathutils.bvhtree import BVHTree

def interpenetrations(low_obj, high_obj, limit: int = 200) -> int:
    bvh_low = BVHTree.FromObject(low_obj, low_obj.users_scene[0])
    bvh_high = BVHTree.FromObject(high_obj, high_obj.users_scene[0])
    return len(bvh_low.overlap(bvh_high)[:limit])
```

### 9.3 익스플로전 베이킹: 축을 고르고 겹친 구간만 민다

원리는 단순하다. **겹치는 부품을 한 축 방향으로 밀어 축 투영을 서로 떼어 놓고 베이크한 뒤, 원래 위치로 되돌린다.** 평행 이동은 탄젠트 공간 노멀에 영향을 주지 않으므로(회전과 달리) 베이크 결과가 유효하다. 이것이 익스플로전이 성립하는 이유다.

축 선택 규칙:

| 클러스터 | 분리 축 | 이유 |
| --- | --- | --- |
| 시트(프레임·쿠션·등받이·벨트) | **Z** | 부품이 위로 쌓여 있어 가장 짧게 떨어진다 |
| 도어(스킨·내장·방음재) | **Y**(차량 좌우) | 판이 겹겹이 쌓인 방향 |
| 대시보드(본체·에어벤트·버튼) | **Y**(차량 전후) | 계기판이 앞뒤로 층을 이룸 |
| 휠(림·타이어·브레이크) | **X**(차축) | 동심원 → 축 방향이 유일 |

간격은 **베이크 해상도와 케이지 여유의 함수**다. 4096 에서 차체 4.6 m 를 덮으면 텍셀 1.1 mm 이므로, 20 mm 간격이면 약 18 텍셀이 확보되어 이웃 부품의 영향이 사라진다. 2048(2.2 mm/texel)에서는 10 mm 면 충분하다.

계산기는 이 작업을 그대로 한다.

```bash
python -m pipeline.vehicle_asset_optimizer explode --demo --axis z --gap 0.02 --unit mm
```

```text
익스플로전 베이킹 오프셋 — z 축, 간격 20 mm, 그룹 1

부품                             그룹                 원래 구간                  이동 후          이동
-----------------------------------------------------------------------------------------
seat_frame                      0     200.000 ~ 360.000     200.000 ~ 360.000      0.000
seat_cushion                    0     280.000 ~ 440.000     380.000 ~ 540.000    100.000
belt_buckle                     0     300.000 ~ 420.000     560.000 ~ 680.000    260.000
backrest                        0     340.000 ~ 900.000    700.000 ~ 1260.000    360.000
headrest                        0    860.000 ~ 1060.000   1280.000 ~ 1480.000    420.000

  이동한 부품 4/5  |  최대 이동 420.000 mm  |  잔여 겹침 0쌍
    [OK  ] 축 투영이 모두 분리됐다 — 이 상태로 베이크하고 원래 위치로 되돌린다
```

알고리즘은 이렇다.

1. 각 부품의 축 구간 `[lo, hi]` 를 정렬한다.
2. 구간이 겹치는(또는 닿는) 부품을 하나의 그룹으로 묶는다.
3. 그룹 안에서 원래 순서대로 `gap` 만큼 띄워 다시 쌓는다. 그룹의 첫 부품은 제자리에 둔다(이동 최소화).
4. 겹치지 않던 부품은 건드리지 않는다.
5. 결과에서 남은 겹침 쌍이 0 인지 확인한다(계산기가 `잔여 겹침` 으로 보고).

블렌더 쪽에서 bbox 를 덤프하는 스크립트는 이렇게 짧다.

```python
import bpy, json

def dump_bounds(objects, path="scene.json"):
    out = []
    for obj in objects:
        corners = [obj.matrix_world @ __import__("mathutils").Vector(c) for c in obj.bound_box]
        lo = [min(c[i] for c in corners) for i in range(3)]
        hi = [max(c[i] for c in corners) for i in range(3)]
        out.append({"name": obj.name, "lo": lo, "hi": hi})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"objects": out}, fh, ensure_ascii=False, indent=2)
```

### 9.4 복원 자동화: 원점은 건드리지 않는다

익스플로전에서 가장 흔한 사고는 **되돌리지 못하는 것**이다. 두 가지만 지키면 된다.

1. **오브젝트 원점(origin)을 건드리지 않고, 위치(translation)만 더한다.** 원점을 옮기면 경첩 축·서스펜션 기준점이 틀어져 엔진 조립이 어긋난다.
2. **이동 전 위치를 이름으로 저장한다.** 되돌릴 때 그대로 대입한다.

```python
import bpy, json
from mathutils import Vector

def explode(objects, offsets: dict[str, float], axis="z"):
    """offsets: {오브젝트 이름: 축 방향 이동량(m)}. 이동 전 위치를 파일로 남긴다."""
    backup = {}
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    for obj in objects:
        backup[obj.name] = list(obj.location)
        delta = Vector((0.0, 0.0, 0.0))
        delta[idx] = offsets.get(obj.name, 0.0)
        obj.location = obj.location + delta
    with open("explode_backup.json", "w", encoding="utf-8") as fh:
        json.dump(backup, fh, ensure_ascii=False, indent=2)


def restore(objects, path="explode_backup.json"):
    with open(path, encoding="utf-8") as fh:
        backup = json.load(fh)
    for obj in objects:
        if obj.name in backup:
            obj.location = Vector(backup[obj.name])
```

복원 검증은 **이동 전 좌표와의 최대 차이 < 1e-6 m** 로 자동 확인한다. `.blend` 파일도 함께 저장해 두면, 스크립트가 실패해도 한 단계 뒤로 갈 수 있다.

### 9.5 `_high`/`_low` 네이밍 매칭과 일괄 베이킹

베이크는 `Selected to Active` 모드에서 **활성(active) 오브젝트가 로우폴리**, 선택된 나머지가 하이폴리다. 이 규칙을 이름으로 강제하면 배치가 안전해진다.

- `{cluster}_High` — 하이폴리(원본, 절차 생성)
- `{cluster}_Low` — 로우폴리(감축·노멀 전송 완료)
- `{cluster}_Cage` — 로우폴리 복제 + Alt+S
- 베이크 이미지: `T_{model}_{cluster}_{normal|ao|orm}`

```python
import bpy

def bake_cluster(low_name: str, high_names: list[str], cage_name: str | None,
                 size: int, samples: int = 512) -> None:
    low = bpy.data.objects[low_name]
    bpy.ops.object.select_all(action="DESELECT")
    for name in high_names:
        bpy.data.objects[name].select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.use_cage = cage_name is not None
    if cage_name:
        scene.render.bake.cage_object = bpy.data.objects[cage_name]
        scene.render.bake.cage_extrusion = 0.0     # 케이지 사용 시 0
    else:
        scene.render.bake.cage_extrusion = 0.002   # 2 mm
        scene.render.bake.max_ray_distance = 0.01  # 케이지 없을 때만 유효

    scene.render.bake.margin = 8                    # 4096 에서 8 px
    scene.render.bake.use_clear = True
    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
```

배치 시간은 계획에 넣어야 한다. 4096 노멀 한 장, 512 샘플, RTX 3080 급에서 클러스터당 **3~8분**(형상 복잡도·디노이즈 설정에 따라 크게 변한다). 18 차종 × 6 클러스터 = 108 회라면 **5~14시간**이다. 이 시간을 줄이는 방법은 세 가지다.

| 방법 | 효과 | 대가 |
| --- | --- | --- |
| 해상도별 분리(외장 4096 / 실내·시트 2048) | 실내·시트 72회가 1/4 시간 | 없음(어차피 해상도가 다르다) |
| AO·ORM 은 256 샘플 | 전체의 약 1/3 절감 | AO 노이즈(디노이즈로 보완) |
| 야간 배치 + 로그 검증 | 사람 시간 0 | 실패 시 다음 날 발견 → 9.2 의 자동 검증으로 보완 |

---

## 10. 광선 놓침: 케이지 표준과 오목·얇은 모서리

광선 놓침(ray miss)은 노멀맵에 **마젠타(또는 검정) 구멍**으로 나타난다. 원인은 거의 항상 "광선이 시작하는 위치"다. 블렌더 Cycles 의 베이크는 LP 표면에서 안쪽으로 광선을 쏘는데, LP 가 HP 보다 안쪽에 있으면 광선이 HP 를 만나기 전에 끝난다.

### 10.1 원인 다섯 가지

| 원인 | 증상 | 확인 |
| --- | --- | --- |
| 케이지 없이 `Extrusion 0` | 곡면 전체에 점 형태 구멍 | 베이크 설정 |
| 케이지/Extrusion 이 너무 작음 | 오목한 곳·모서리에만 구멍 | 10.3 의 여유 검사 |
| `Max Ray Distance` 부족 | 큰 굴곡에서 띠 모양 구멍 | 값을 0(무제한)으로 바꿔 비교 |
| 오목 모서리에서 자기 면에 먼저 맞음 | 홈 안쪽에 검은 줄 | 케이지 버텍스 조정 |
| 얇은 판(두께 < 오프셋) | 판 중앙에 반대편 무늬 | 두께 측정, 오프셋 축소 |

### 10.2 케이지 표준 제작

케이지는 "로우폴리를 복제해 바깥으로 부풀린 메시"다. 블렌더 매뉴얼도 같은 절차를 안내한다: 로우폴리를 복제하고, `Alt+S`(Shrink/Fatten, 노멀 방향)로 부풀려 하이폴리를 완전히 감싸게 만든 뒤, 필요한 곳만 손으로 조정한다. **토폴로지(면 수·순서)가 로우폴리와 같아야** 베이커가 대응시킬 수 있다.

절차:

```
① Low 복제 (Shift+D, 이름 {cluster}_Cage)
② Edit Mode → A(전체 선택)
③ Alt+S → 부품 최소 특징의 1~3배로 부풀림
   · Offset Even 켜기: 곡률이 균일하게 유지된다(끄면 꼭짓점이 과하게 밀린다)
   · Shade Smooth 상태에서 부풀리기: 하드 엣지가 갈라져 있으면 부푼 양이 불균일해진다
④ 홈·모서리만 손으로 내리기(버텍스 선택 → G 또는 Alt+S)
⑤ 검증: 케이지가 HP 를 감싸는지, 자기 교차가 없는지 (10.5)
```

> **함정**: 케이지 단계에서는 `Edge Split`·마크된 샤프 엣지에 의해 노멀이 갈라져 있으면 `Alt+S` 가 그 자리에서 메시를 찢는다. 케이지용 복제본에서만 샤프 마크를 잠시 해제하고, 부풀린 뒤 되돌린다.

### 10.3 케이지 vs Max Ray Distance

| 항목 | Extrusion + Max Ray Distance | Cage Object |
| --- | --- | --- |
| 정밀도 | 낮음(전체에 균일 오프셋) | 높음(부위별 조정) |
| 준비 비용 | 0 | 복제 + 수동 조정(부품당 10~30분) |
| 오목부 처리 | 불가(오목부에서 자기 면에 맞음) | 가능(해당 버텍스만 내림) |
| 얇은 판 | 위험(반대편을 먼저 맞음) | 가능(판 두께 이하로 조정) |
| 반복 수정 | 값만 바꾸면 됨 | 메시 수정 필요 |
| 자동화 | 쉬움 | 어려움(부위별 데이터 필요) |
| 병용 | **불가** — 케이지를 쓰면 `Max Ray Distance` 는 비활성 | — |

마지막 줄이 중요하다. 블렌더 매뉴얼은 "Ray distance is only available when not using Cage" 라고 명시한다. 케이지를 켜는 순간 광선의 시작점과 끝은 **케이지 형상이 전부** 결정하므로, 케이지가 잘못되면 설정값으로 구제할 수 없다.

실무 판단:

- **차체·도어·후드**: 케이지 필수(곡률이 크고 패널 라인이 많다).
- **실내·시트**: 케이지 권장(부품이 밀착되어 9장과 겹친다).
- **휠·램프**: Extrusion + 무제한 Ray Distance 로 충분(형상이 단순하고 볼록하다).
- **유리**: 노멀 베이크를 하지 않으므로 해당 없음.

### 10.4 오목 모서리와 얇은 모서리의 인터섹션

LP 가 오목한 홈(그릴 슬롯, 창틀 홈, 도어 손잡이 오목)을 가지면, 그 안쪽의 두 면이 각각 바깥으로 부풀면서 **케이지끼리 서로를 뚫는다.** 그러면 광선이 옆면에서 시작해 엉뚱한 면을 맞는다.

방지 순서:

1. **홈 안쪽 버텍스는 부풀리지 않는다.** 버텍스 그룹(`Cage_NoInflate`)을 만들어 `Alt+S` 전에 가중치 0 으로 두거나, 부풀린 뒤 해당 버텍스만 원위치로 되돌린다.
2. **홈 깊이의 1/2 을 최대 오프셋으로 잡는다.** 홈 깊이 6 mm 면 오프셋 ≤ 3 mm.
3. **얇은 판은 두께의 1/2 이하.** 도어 스킨 1.5 mm 면 오프셋 ≤ 0.7 mm. 이때는 케이지 대신 **LP 를 HP 쪽으로 살짝 옮기는 방법**이 낫다(4.3 `Offset`).
4. **자기 교차를 검사한다.** 케이지 자체가 자기를 뚫으면 그 자리는 반드시 실패한다.

```python
from mathutils.bvhtree import BVHTree

def cage_self_intersections(cage_obj, scene) -> int:
    bvh = BVHTree.FromObject(cage_obj, scene)
    return len(bvh.overlap(bvh))
```

### 10.5 케이지 검증: 경계 상자로 90% 를 잡는다

케이지의 실패는 대개 두 방향이다. **너무 붙었다**(광선 놓침) 또는 **너무 멀었다**(옆 부품·반대편을 먼저 맞음). 경계 상자만으로도 이 두 극단과 토폴로지 불일치는 잡힌다. 계산기의 `cage` 명령이 그 검사다.

```bash
python -m pipeline.vehicle_asset_optimizer cage --demo
```

```text
케이지 검증 — OK
  low  door_low                1840 verts
  high door_high             412000 verts
  cage door_cage               1840 verts

  [OK  ] 1840 = low 1840        케이지가 로우폴리와 같은 버텍스 수다
  [OK  ] +1.0%                  케이지가 하이폴리를 모든 축에서 감싼다
  [OK  ] 1.00%                  케이지 여유가 권장 범위 안이다
  [OK  ] 모든 축                   케이지가 로우폴리 바깥에 있다
  [OK  ] high ⊄ low             하이폴리가 실루엣에서 로우폴리를 벗어난다

  축별 여유 x:+1.00%  y:+7.27%  z:+1.33%
```

여유의 단위는 **하이폴리 크기 대비 비율**이다. 절대 mm 로 두면 큰 부품과 작은 부품에 같은 기준을 적용할 수 없다.

| 여유 | 판정 | 의미 |
| --- | --- | --- |
| < 0.4% | WARN | 오목한 곳에서 광선을 놓칠 확률이 높다 → `Alt+S` 한 번 더 |
| 0.4~35% | OK | 표준. 차체는 1~5%, 시트는 5~15% 가 실무값 |
| > 35% | WARN | 옆 부품·반대편을 먼저 맞고, 베이크 시간이 늘고, 곡면이 밀려 보인다 |

---

## 11. 탄젠트 어긋남과 익스포트 3c 규칙

탄젠트 공간 노멀맵은 **"이 면의 탄젠트·바이탄젠트·노멀"이라는 좌표계 위에 적힌 벡터**다. 그래서 노멀맵 자체는 맞는데 화면에서 조명이 틀어지는 일이 생긴다. 좌표계를 만드는 규칙이 블렌더와 엔진에서 미묘하게 다르기 때문이다.

### 11.1 MikkTSpace: 표준이 있지만, 입력이 같아야 결과가 같다

MikkTSpace 는 UV 와 버텍스 노멀에서 탄젠트 기저를 만드는 **참조 구현·표준**이다. 블렌더는 이 계열의 구현을 쓰고, UE5 도 탄젠트 생성 방식으로 MikkTSpace 를 제공한다(임포트 옵션의 `Normal Generation Method`). 이론적으로 같은 입력이면 같은 결과가 나온다. 어긋나는 것은 **입력이 달라질 때**다.

| 어긋나는 원인 | 무슨 일이 생기나 | 대응 |
| --- | --- | --- |
| 삼각화 방향 차이 | 비평면 사각형의 대각선이 달라져 탄젠트가 회전 → 대각선 이음 | 익스포트 전 Triangulate(11.2) |
| 노멀 소스 차이 | 커스텀 노멀 vs 재계산 노멀 → 탄젠트 기저 자체가 다름 | 노멀 재계산 끄기(11.4) |
| G 채널 규약 | OpenGL(위쪽 +Y) vs DirectX(아래쪽 -Y) → 요철이 반대로 보임 | 베이크 시 G=-Y 또는 엔진에서 Flip Green |
| 미러 UV·음수 스케일 | 바이탄젠트 부호가 뒤집혀 한쪽 면만 어긋남 | 미러는 UV 를 별도 섬으로, 스케일 Apply |
| UV 스케일 극단값 | 삼각형이 UV 에서 찌그러져 탄젠트가 불안정 | 패널 단위 재언랩, 텍셀 밀도 균일화 |

### 11.2 삼각화는 익스포트 전에 반드시

블렌더는 사각형·n-gon 을 그대로 저장할 수 있고, 엔진 임포터는 그것을 자기 방식으로 삼각화한다. **비평면 사각형(non-planar quad)은 대각선 선택에 따라 두 삼각형의 노멀·탄젠트가 달라진다.** 곡면 차체는 거의 모든 사각형이 비평면이므로, 이 차이가 곧 대각선 이음으로 나타난다.

```
사각형 ABCD (비평면)
   블렌더 삼각화: ABC + ACD         엔진 삼각화: ABD + BCD
        │                                 │
   같은 노멀맵, 다른 탄젠트 기저 → 대각선을 따라 하이라이트가 꺾인다
```

규칙:

1. 익스포트 직전에 **Triangulate 모디파이어를 Apply** 한다(`Quad Method: Beauty`, `Keep Custom Normals: ON`).
2. `Keep Custom Normals` 를 끄면 5장에서 전송한 커스텀 노멀이 사라진다. 반드시 켠다.
3. 삼각화 후 **삼각형 수를 다시 기록**한다(사각형 1개 → 삼각형 2개). 예산 검증을 삼각화 후에 한다.
4. 엔진에서 `Recompute Normals`·`Recompute Tangents` 를 끈다(11.4).

### 11.3 FBX 익스포트 설정 (블렌더 4.x/5.x)

| 항목 | 값 | 이유 |
| --- | --- | --- |
| Object Types | `Mesh` 만 | 카메라·라이트·빈이 딸려 들어가면 임포트가 지저분해진다 |
| Selected Objects | ON | 클러스터 단위 익스포트 |
| Apply Modifiers | ON | Triangulate·Shrinkwrap 이 이미 Apply 되었으면 무해. Evaluate 상태를 보장 |
| Smoothing | `Face`(또는 `Edge`) | 커스텀 노멀을 쓰면 `Face` 로 충분 |
| Tangent Space | **ON** | 탄젠트를 파일에 기록해야 엔진이 재계산하지 않는다 |
| Vertex Colors | **없음** | 3c ① |
| Apply Unit | ON, Scale 1.0 | 100배/0.01배 스케일 사고 방지 |
| Forward / Up | `-Z` / `Y` | UE 기본 축 |
| Bake Space Transform | OFF | 축 변환을 메시에 구우면 탄젠트도 함께 회전한다. 축 변환은 임포터가 한다 |
| Triangulate(익스포트 옵션) | 사용하지 않음 | 이미 Apply 했으므로 이중 삼각화를 피한다 |

```python
import bpy

bpy.ops.export_scene.fbx(
    filepath="//export/door_Low.fbx",
    use_selection=True,
    object_types={"MESH"},
    use_mesh_modifiers=True,
    mesh_smooth_type="FACE",
    use_tspace=True,              # Tangent Space
    apply_unit_scale=True,
    axis_forward="-Z",
    axis_up="Y",
    bake_space_transform=False,
    add_leaf_bones=False,
    path_mode="COPY",
    embed_textures=False,
)
```

### 11.4 엔진 임포트 설정

UE 의 FBX 임포트에는 노멀·탄젠트 관련 옵션이 세 층으로 나뉜다. (1) 임포트 시 `Normal Import Method`, (2) 임포트 시 `Normal Generation Method`, (3) 임포트 후 스태틱 메시의 Build Settings.

| 항목 | 값 | 이유 |
| --- | --- | --- |
| Normal Import Method | **Import Normals and Tangents** | FBX 에 기록된 노멀·탄젠트를 그대로 사용 → 베이크한 탄젠트 베이스와 일치 |
| Normal Generation Method | `MikkTSpace` | 위 옵션이 `Compute Normals` 로 떨어질 때만 쓰인다. 기본값을 MikkTSpace 로 둔다 |
| Compute Weighted Normals | OFF | 가중 노멀은 커스텀 노멀을 덮어쓴다 |
| Recompute Normals (Build Settings) | **OFF** | 3c ② |
| Recompute Tangents (Build Settings) | **OFF** | 3c ③ |
| Use MikkTSpace Tangent Space | ON | 재계산이 필요한 경우의 기준 |
| Transform Vertex to Absolute | OFF | 원점 유지(조립 기준점) |
| Convert Scene / Convert Scene Unit | ON / ON | 스케일 함정 방지(아래) |
| Import Mesh LODs | ON | 클러스터별 LOD 를 함께 임포트 |
| Flip Green Channel (텍스처 에셋) | 베이크 규약과 반대로 구웠을 때만 ON | 11.5 |

**스케일 함정**: 블렌더 기본 단위는 m, UE 는 cm 다. `Apply Unit` 과 임포터의 `Convert Scene Unit` 조합이 어긋나면 차가 100배 또는 1/100 로 들어온다. 검증은 **정확히 100 cm 짜리 큐브를 함께 익스포트**해서 엔진에서 100 uu 인지 보는 것이다. 이 검증용 큐브를 파이프라인에 넣어 두면 매번 확인할 필요가 없다.

### 11.5 "3c 건너뛰기" 규칙

`3c` 는 이 프로젝트에서 쓰는 **익스포트 단계의 세 가지 "건너뛰기"** 를 가리키는 말이다. 외부 표준 용어가 아니므로 팀 문서에 정의를 고정해 둔다.

| # | 건너뛸 것 | 왜 건너뛰는가 | 어기면 |
| --- | --- | --- | --- |
| ① Color | 버텍스 컬러 채널을 내보내지 않는다 | 색은 텍스처(Albedo·ORM)가 담당한다. FBX 버텍스 컬러는 파일·메모리를 늘리고 엔진에서 마스크·틴트로 오인된다 | 페인트가 이중으로 어두워지거나, 머티리얼에 불필요한 노드가 생긴다 |
| ② Recompute Normals | 노멀 재계산을 끈다 | 재계산은 5장에서 전송한 커스텀 스플릿 노멀을 덮어쓴다 | 패널 라인이 뭉개지고 하이라이트가 각져 보인다 |
| ③ Tangent 재계산 | 탄젠트 재계산·공간 변환을 끈다 | 재계산하면 베이크 당시와 다른 탄젠트 기저가 되어 노멀맵이 기운다 | 대각선 이음·좌우 비대칭 조명 |

세 항목은 서로 독립이지만 **함께 어겨지는** 경우가 많다. 익스포트 프리셋 하나(`Vehicle_LP_3c`)를 만들어 팀 전체가 같은 값을 쓰게 하는 것이 유일한 예방책이다.

### 11.6 어긋남 진단: 두 장의 테스트 맵

원인을 좁히는 데는 두 장이면 충분하다. 엔진에 임포트해 차체 대신 구·원통에 붙여 본다.

| 테스트 맵 | 만드는 법 | 무엇을 보는가 |
| --- | --- | --- |
| **평면 노멀**(0.5, 0.5, 1.0) | 4 px 짜리 단색 이미지 | 이 맵에서 조명이 튀면 노멀맵이 아니라 탄젠트·노멀 설정 문제다 |
| **UV 체커 + 그라디언트** | UV 체커에 방향별 색 그라디언트를 굽는다 | 원통에서 링 무늬가 비틀리면 탄젠트 어긋남, 좌우가 반대면 G 채널 |

진단 순서:

```
① 평면 노멀맵 → 조명 정상?  ── 아니오 ─▶ 노멀 소스/재계산 문제 (11.4 ②③)
        │ 예
② 체커+그라디언트 → 링이 비틀림? ── 예 ─▶ 삼각화/UV (11.2, 11.1)
        │ 아니오
③ 실제 노멀맵 → 요철이 반대? ── 예 ─▶ G 채널 (11.1)
        │ 아니오
④ 곡면만 어긋남 ──▶ 커스텀 노멀 전송 순서 (5.3)
```

---

## 12. 계산 규칙: MiB, 밉 체인, 블록 4×4

VRAM 계산이 틀리는 이유는 대개 세 가지다. 단위, 밉 체인, 그리고 "압축 후 크기"의 오해.

### 12.1 세 가지 함정

| 함정 | 흔한 계산 | 실제 | 오차 |
| --- | --- | --- | --- |
| MiB vs MB | 18 차종 "1.44 GB" | 1,440 MiB = 1.51 GB(십진) | 4.9% (단위 혼동) |
| 밉 체인 누락 | 4096² 한 장 = 16 MiB | 21.33 MiB | **25% 낙관적** |
| bpp 혼동 | BC7 = 4 bpp | BC7 = 8 bpp (블록 16 B / 4×4 텍셀) | 2배 |

### 12.2 공식

```
블록 압축(BC1/BC4/BC5/BC6H/BC7):
    베이스 밉 = ceil(W/4) × ceil(H/4) × bytes_per_block
    밉 체인  = Σ (단계별 크기), 마지막 3단(4×4, 2×2, 1×1)도 각각 1블록
    총합     ≈ 베이스 × 4/3

비압축(R8, RGBA8, RGBA16F):
    베이스 = W × H × bpp/8
```

| 포맷 | bpp | 4096² (밉 포함) | 2048² (밉 포함) | 1024² (밉 포함) |
| --- | --- | --- | --- | --- |
| BC1 | 4 | 10.67 MiB | 2.67 MiB | 0.67 MiB |
| BC4 | 4 | 10.67 MiB | 2.67 MiB | 0.67 MiB |
| BC5 | 8 | 21.33 MiB | 5.33 MiB | 1.33 MiB |
| BC7 | 8 | 21.33 MiB | 5.33 MiB | 1.33 MiB |
| BC6H | 8 | 21.33 MiB | 5.33 MiB | 1.33 MiB |
| RGBA8 | 32 | 85.33 MiB | 21.33 MiB | 5.33 MiB |

```bash
python -m pipeline.vehicle_asset_optimizer formats
```

블록 4×4 규칙은 해상도가 4의 배수가 아니면 낭비를 만든다. 1023×1023 은 256×256 블록(65,536 × 16 B = 1,048,576 B)으로 계산되는데 실제 텍셀은 1,046,529 개뿐이므로 0.2% 를 버린다. 크기는 작지만, 밉 체인이 1023 → 511 → 255 … 로 내려가면서 이 1 픽셀 부족이 매 단계마다 따라온다. **항상 2의 거듭제곱을 쓴다.**

### 12.3 소스 크기와 런타임 크기는 무관하다

4K PNG 원본이 60 MB 라는 것은 디스크·쿡 시간 이야기이고, VRAM 은 압축 포맷 크기다. 반대로 **쿡된 패키지 크기**는 VRAM 과 거의 같다(플랫폼 압축 후). 계획할 때 두 숫자를 섞으면 "18 차종이 4 GB 니까 안 된다" 같은 잘못된 결론이 나온다.

| 구분 | 18 차종 × 6장 (4096 3 + 2048 3) | 비고 |
| --- | --- | --- |
| 소스 아트(16bit PNG/TGA) | 4~8 GB | 형식·압축에 따라 크게 다르다 |
| 쿡 결과(pak) | 약 1.4 GiB | VRAM 상주량과 같다 |
| VRAM 상주(밉 포함) | 1,440 MiB | 13장의 계산 |

---

## 13. 차종 18개의 텍스처 상주량 실측 계산

차량 한 대의 텍스처는 **차종**에 딸린다. 대수에 딸리지 않는다. 2,000대가 같은 차종 18개를 공유하면 텍스처는 18세트만 존재한다. 이 사실이 "2,000대면 감당 가능한가"라는 질문의 답을 바꾼다.

### 13.1 차종당 구성

| 세트 | 해상도 | 맵 | 포맷 | 장당(밉 포함) | 소계 |
| --- | --- | --- | --- | --- | --- |
| 외장 | 4096² | Normal(탄젠트) | BC5 | 21.33 MiB | |
| | | Albedo(도색) | BC7 | 21.33 MiB | |
| | | ORM | BC7 | 21.33 MiB | **64.00 MiB** |
| 실내·시트 | 2048² | Normal | BC5 | 5.33 MiB | |
| | | Albedo | BC7 | 5.33 MiB | |
| | | ORM | BC7 | 5.33 MiB | **16.00 MiB** |
| **차종당 합계** | | | | | **80.00 MiB** |

AO 는 별도 텍스처가 아니라 ORM 의 R 채널에 들어 있다(14장). 이것이 64 MiB 라는 숫자를 만든 핵심 결정이다.

### 13.2 18 차종

```
18 차종 × 80 MiB = 1,440 MiB = 1.406 GiB
1,440 MiB / 10,240 MiB (RTX 3080 10 GiB) = 14.1%
```

브리프에 적힌 "약 1.44 GB / 14.4%"는 같은 계산을 **십진 단위(1,440 MB / 10 GB)** 로 반올림한 값이다. 어느 쪽으로 적어도 결론은 같다: **차량 텍스처는 예산의 14% 수준으로, 10 GiB 에서 여유가 크다.**

```bash
python -m pipeline.vehicle_asset_optimizer vram --chassis 18 --exterior 4096 --interior 2048
```

```text
차량 텍스처 VRAM 예산 — 예산 10,240 MiB, 차종 18개, 2,000대 (밉 포함)

[exterior@4096] 3장
  normal 4096x4096 BC5                    16.00 + 밉  5.33 =   21.33 MiB
  albedo 4096x4096 BC7                    16.00 + 밉  5.33 =   21.33 MiB
  orm 4096x4096 BC7                       16.00 + 밉  5.33 =   21.33 MiB
  합계                                                      64.00 MiB

[interior@2048] 3장
  normal 2048x2048 BC5                     4.00 + 밉  1.33 =    5.33 MiB
  albedo 2048x2048 BC7                     4.00 + 밉  1.33 =    5.33 MiB
  orm 2048x2048 BC7                        4.00 + 밉  1.33 =    5.33 MiB
  합계                                                      16.00 MiB

차종당 합계    80.00 MiB  x18 = 1,440.0 MiB
  예산 대비  14.1%  |  남는 양 8,800.0 MiB  |  판정 여유
인스턴스 버퍼 2,000 x 256 B = 0.49 MiB

절감 시나리오 (양수 = 줄어드는 양)
  실내 2048→1024 (디테일 노멀 타일로 대체)              1,224.0 MiB  (+216.0 MiB,  11.9%)
  외장 4096→2048                                576.0 MiB  (+864.0 MiB,   5.6%)
  ORM → AO/Roughness/Metallic 3장(BC4) 분리(음수 = 증가)  1,680.0 MiB  (-240.0 MiB,  16.4%)
  외장·실내 모두 절반(최소 예산)                          360.0 MiB  (+1,080.0 MiB,   3.5%)

  · 계산 단위: 1 MiB = 1,048,576 B, 밉 체인 포함.
  · 텍스처 상주량은 차종 수에만 비례한다 — 2,000대여도 18차종이면 18세트만 메모리에 있다.
  · 인스턴스 버퍼: 2,000대 x 256 B = 0.49 MiB (텍스처의 0.03%).
  · 예산 10,240 MiB 중 차량 텍스처가 1,440 MiB = 14.1%.
  · 밉 체인은 베이스 밉의 약 33% 를 더 쓴다(4/3). 밉을 빼고 계산하면 25% 낙관적이 된다.
```

### 13.3 이 계산이 틀어지는 세 가지 경우

| 경우 | 결과 | 대응 |
| --- | --- | --- |
| 도색을 텍스처로 만든다 | 차종 × 도색 수로 곱해진다(18 × 8색 = 144세트 = 11.25 GiB) | 도색은 **파라미터**(인스턴스 커스텀 데이터·Material Parameter)로 |
| 차종이 18 → 40 으로 는다 | 3,200 MiB (31%), 예산이 빠듯해진다 | 외장 4096 → 2048 검토(-864 MiB) |
| 실내를 4096 으로 올린다 | 차종당 128 MiB, 2,304 MiB (22.5%) | 17장의 타일 전략으로 해상도를 낮춘다 |

**도색을 텍스처로 만들지 않는 것**이 이 예산에서 가장 큰 단일 결정이다. 도색·번호판·웨어/더트는 인스턴스 커스텀 데이터(15장)로 넘기고, Albedo 에는 중립 회색 마스크만 둔다.

---

## 14. ORM 채널 패킹: 3장을 1장으로

AO·Roughness·Metallic 은 모두 회색조다. 따로 저장하면 텍스처 3장, 샘플러 3개, 스트리밍 단위 3개를 쓴다. 한 장의 RGB 에 밀어 넣으면 **1장, 1샘플러**가 된다.

```
ORM 텍스처 (BC7, sRGB OFF)
  R = Ambient Occlusion     (텍스처가 있으면 곱, 없으면 1)
  G = Roughness
  B = Metallic
```

### 14.1 절감률: 어떤 포맷으로 저장했느냐에 달렸다

| 분리 저장 구성 | 3장 합계 | ORM 1장 | 절감 |
| --- | --- | --- | --- |
| 3 × BC7 (8 bpp) | 64.00 MiB | 21.33 MiB | **66.7%** |
| 3 × BC4 (4 bpp, 회색조 정석) | 32.00 MiB | 21.33 MiB | 33.3% |
| 3 × R8 (비압축) | 64.00 MiB | 21.33 MiB | 66.7% |

브리프의 "66% 절감"은 첫 줄(3장을 모두 BC7 로 저장했을 때) 기준이다. 회색조를 제대로 BC4 로 골라 저장했다면 바이트 기준 절감은 33% 다. **그래도 패킹해야 하는 이유**는 바이트보다 샘플러·스트리밍·머티리얼 노드 수다.

```bash
python -m pipeline.vehicle_asset_optimizer packing --resolution 4096
```

```text
채널 패킹 비교 — 4096x4096

  분리  ao 4096x4096 BC7                    21.33 MiB
  분리  roughness 4096x4096 BC7             21.33 MiB
  분리  metallic 4096x4096 BC7              21.33 MiB
  분리 합계                              64.00 MiB

  패킹  orm 4096x4096 BC7                   21.33 MiB
  패킹 합계                              21.33 MiB

  절감 66.7%  (42.67 MiB 절약)
```

계산기의 `vram` 시나리오가 ORM 분리 시 **-240 MiB(증가)** 를 보여주는 것은, 분리를 BC4(4 bpp)로 가정하기 때문이다. 즉 "BC4 로 잘 저장한 3장(12 bpp) vs ORM BC7 1장(8 bpp)" 이고, 이 비교에서도 패킹이 33% 이익이다. 어느 가정에서도 패킹이 손해인 경우는 없다.

### 14.2 ORM 작성 규칙

| 규칙 | 이유 |
| --- | --- |
| sRGB **끄기**(선형) | Roughness·Metallic·AO 는 색이 아니라 데이터다. sRGB 로 읽으면 값이 왜곡된다 |
| 채널마다 독립적으로 굽는다 | AO 는 Cycles AO, Roughness/Metallic 은 HP 머티리얼에서. 한 번에 구우면 섞인다 |
| BC7 사용 | BC1 은 채널당 5:6:5 로 압축해 Roughness 계단이 생긴다. 금속 러프니스 범위가 넓다 |
| AO 범위는 0.3~1.0 으로 리맵 | 순수 0 은 접지부를 검게 만든다(실내·시트에서 특히) |
| 채널별 통계 검증 | R/G/B 평균·표준편차가 0 에 붙으면 채널이 비어 있다(머티리얼 노드 누락) |

`pipeline/texture_packer.py` 의 `verify()` 가 이 통계 검증을 한다. 차량에서는 ORM 을 채널별로 굽기 때문에, **B 채널(금속)이 0.9 이상으로 뭉쳐 있으면** 도색 부위에 금속을 잘못 넣은 것이다.

---

## 15. 2,000대 인스턴싱의 메모리와 드로우콜

2,000대를 배치하는 비용은 텍스처가 아니라 **인스턴스 데이터와 드로우콜**이다. 그리고 이 둘은 모두 작다. 진짜 비용은 그림자·컬링·LOD 전환이다.

### 15.1 인스턴스 버퍼

| 요소 | 바이트/대 | 2,000대 | 비고 |
| --- | --- | --- | --- |
| Transform (float3x4) | 48 | 96 KB | 회전·스케일 포함 |
| 커스텀 데이터(도색 ID, 번호판, 웨어/더트) | 16~64 | 32~128 KB | 인스턴스별 파라미터 |
| 패딩·플래그·LOD | 32~128 | 64~256 KB | 정렬·배칭 단위 |
| **합계** | **128~256** | **0.25~0.5 MiB** | 텍스처의 0.03% 수준 |

```
2,000 × 256 B = 512,000 B = 0.49 MiB
```

텍스처(1,440 MiB)와 비교하면 3만 배 작다. **"2,000대"는 메모리 문제가 아니다.** 메모리 문제는 차종 수와 해상도에서 온다.

### 15.2 드로우콜과 Nanite

| 구성 | 메시 수 | 드로우콜(개략) | 비고 |
| --- | --- | --- | --- |
| 차종 18 × 클러스터 6 | 108 | 108~250 | 머티리얼 슬롯 수만큼 늘어난다 |
| HISM 1개 per (차종, 클러스터) | 108 | 위와 동일 | 인스턴스는 한 번에 그린다 |
| Nanite 사용 시 | 108 | 클러스터 배치 단위 | GPU 컬링·LOD 자동, 인스턴스 culling 지원 |

Nanite 는 인스턴스 수에 강하다. 2,000대를 108 메시로 그려도 드로우콜은 수백 수준이고, 컬링은 GPU 에서 일어난다. 대신 다음을 확인한다.

- **가려진 차량의 그림자**: 2,000대가 그림자를 만들면 VSM(가상 섀도우 맵) 페이지가 병목이 된다. 거리 기반 그림자 컬링(예: 60 m 밖 그림자 off)과 `r.Shadow.Virtual.Enable` 설정 확인.
- **LOD 전환**: 실내 클러스터는 30 m 에서 사라져야 한다. 클러스터 분할(6.2 규칙 4)이 이를 가능하게 한다.
- **애니메이션**: 바퀴 회전·서스펜션은 인스턴스 정적 변환으로 처리할 수 없다. 스켈레탈 또는 별도 컴포넌트로 분리하고, 그 수를 줄인다(플레이어 주변 50대만 스켈레탈, 나머지 정적).

### 15.3 도색·번호판을 텍스처로 만들지 않는다

| 항목 | 텍스처로 만들면 | 인스턴스 데이터로 만들면 |
| --- | --- | --- |
| 도색 8색 | 18 차종 × 8 = 144 세트(11.5 GiB) | 차종당 1 세트 + 색상 파라미터 |
| 번호판 | 차량마다 유니크 텍스처(불가능) | 커스텀 데이터 + 데칼 1장 공유 |
| 웨어/더트 | 차종 × 단계 수 | 마스크 1장 + 스칼라 |

같은 원리의 구현은 [오픈월드 콘텐츠 매뉴얼 1장](open_world_content_and_architecture_guide.md)(Chaos Vehicles·탈것)과 [PBR 파이프라인 4장](pbr_material_pipeline.md)(채널 패킹)을 함께 본다.

---

## 16. 가상 텍스처링과 밉 스트리밍 풀

1,440 MiB 를 전부 상주시킬 필요는 없다. 화면에 보이는 차량은 수십 대이고, 그중 4096 밉 0단이 필요한 것은 근접한 몇 대뿐이다. 스트리밍이 이 차이를 회수한다.

### 16.1 밉 스트리밍의 동작

| 단계 | 무슨 일이 일어나나 | 확인 |
| --- | --- | --- |
| 요청 | 카메라 거리·화면 크기로 필요한 밉 계산 | `stat streaming` |
| 풀 할당 | 스트리밍 풀(예산) 안에서 밉 업로드 | `r.Streaming.PoolSize` |
| 초과 | 풀을 넘으면 낮은 밉으로 강제 | 텍스처 뭉개짐, `stat streaming` 경고 |
| 해제 | 화면에서 사라지면 밉 아웃 | `stat streaming` |

풀 크기는 프로젝트 세팅(Engine → Rendering → Textures 의 스트리밍 풀)과 `r.Streaming.PoolSize`(MiB)로 정한다. `[TextureStreaming] PoolSizeVRAMPercentage` 를 쓰는 구성도 있으므로 **프로젝트에서 실제로 어떤 값이 적용되는지 콘솔로 확인**해야 한다(엔진 버전·디바이스 프로파일에 따라 다르다).

권장:

| 항목 | 값 | 이유 |
| --- | --- | --- |
| `r.Streaming.PoolSize` | **1,024~1,536** | 차량 1,440 MiB + 환경 일부를 감당. 4K 해상도에서 10 GiB 예산의 10~15% |
| 밉 바이어스 | 차량 텍스처 그룹만 0 | 도색·노멀은 근접에서 화질이 중요하다 |
| 텍스처 그룹 | `TEXTUREGROUP_Vehicle`(커스텀) | 차량만 따로 LOD 바이어스·최대 해상도를 관리 |
| 논스트리밍 텍스처 | UI·폰트만 | 논스트리밍이 많으면 풀이 압박받는다(`stat streaming` 의 nonstreaming) |

### 16.2 가상 텍스처링: 차량에는 쓰지 않는다

가상 텍스처링(VT)은 큰 텍스처를 타일로 나눠 필요한 부분만 올린다. 이론적으로 차량에 딱 맞지만, 실무에서는 세 가지 이유로 **환경 전용**으로 두는 편이 안전하다.

1. **차량 텍스처는 이미 작다.** 21 MiB 짜리 4096 은 VT 의 이득(수백 MB 텍스처)이 거의 없다.
2. **엔진 버전별 지원 상태가 다르다.** 스트리밍 VT 는 버전에 따라 지원 범위가 바뀌어 왔고, RVT 는 런타임 생성 텍스처용이다. 차량 파이프라인을 여기에 묶으면 엔진 업그레이드가 곧 재작업이다.
3. **VT 는 GPU 비용과 함께 온다.** 인스턴스 2,000대에서 페이지 테이블 갱신은 공짜가 아니다.

VT 는 지형·건물처럼 "한 장이 수 GB" 인 대상에 쓰고(환경은 RVT 로), 차량은 **밉 스트리밍 + 커스텀 텍스처 그룹**으로 관리한다.

```text
권장 구성
  환경(지형·건물)  : RVT / VT, 풀은 엔진 기본
  차량(18 차종)     : 일반 텍스처 + 밉 스트리밍, TEXTUREGROUP_Vehicle, 풀 1,024~1,536 MiB
  UI·폰트           : 논스트리밍(작다)
```

---

## 17. 실내 2048을 1024로: 디테일 노멀 타일 전략

실내는 화면에서 멀고 어둡다. 그런데 2048 3장은 외장의 25%(16/64 MiB)를 쓴다. 여기서 회수할 수 있는 것이 216 MiB(계산기 시나리오)다.

### 17.1 왜 1024로 줄여도 되는가: 텍셀 밀도로 따진다

| 대상 | 실제 크기 | 해상도 | 텍셀 밀도 | 판정 |
| --- | --- | --- | --- | --- |
| 대시보드 상판 | 1.4 m × 0.4 m | 2048² | 1,460 px/m | 과잉(400~600 px/m 이면 충분) |
| 대시보드 상판 | 1.4 m × 0.4 m | 1024² | 731 px/m | 적정 |
| 시트 쿠션 1개 | 0.5 m × 0.5 m | 1024² | 2,048 px/m | 과잉 |
| 도어 내장 패널 | 1.0 m × 0.7 m | 1024² | 1,024 px/m | 적정 |

실내는 UV 를 여러 패널로 나눠 쓰므로, 1024 한 장이 실제로 덮는 면적은 2~4 m² 다. 그러면 512~1,024 px/m 가 되고, 이는 1~3 m 관찰 거리에서 충분하다(3 m 에서 1080p 의 1 px ≈ 3 mm, 512 px/m = 2 mm/texel).

### 17.2 손실을 메우는 디테일 노멀 타일

1024 로 줄이면 가죽 결·스티치·플라스틱 널링 같은 **반복 디테일**이 사라진다. 이것은 개별 텍스처가 아니라 **타일**로 넣는다.

| 요소 | 권장 | 이유 |
| --- | --- | --- |
| 타일 해상도 | 512² | 반복 패턴은 고해상도가 필요 없다 |
| 포맷 | BC5 | 탄젠트 노멀, 타일이므로 밉 체인 필수 |
| UV | 타일 UV(스케일 4~16배) | 0~1 에 매핑하면 반복이 보인다 |
| 블렌드 | 거리 기반 강도(근접 1.0, 2 m 0.5, 4 m 0) | 원거리에서 무아레 방지 |
| 개수 | 3~5장(가죽·직물·플라스틱·카펫) | 실내 전체가 공유 |
| 메모리 | 3~5 × 1.33 MiB = 4~7 MiB | 216 MiB 절감 대비 무시할 수준 |

구현은 머티리얼에서 두 노멀을 합성한다(디테일 노멀을 탄젠트 공간에서 더한 뒤 정규화, 또는 `BlendAngleCorrectedNormals`). 주의할 점:

- **타일 경계에서 밉이 무너진다.** 밉맵이 타일 경계를 넘어 샘플되면 이음이 보인다. 텍스처를 2×2 타일링(같은 이미지를 4번 반복 저장)하거나 `MipValue` 를 수동으로 올린다.
- **디테일 노멀은 탄젠트 공간이어야 한다.** 오브젝트 공간으로 만들면 회전 시 어긋난다.
- **AO 를 다시 굽지 않는다.** 타일 디테일에는 AO 가 없다. 접지부 AO 는 1024 ORM 의 R 채널이 담당한다.

### 17.3 절감 정리

| 시나리오 | 18 차종 실내 합계 | 절감 | 판정 |
| --- | --- | --- | --- |
| 2048 × 3 (기준) | 288 MiB | — | 과잉 |
| 1024 × 3 + 타일 4장 | 72 + 5.3 = 77 MiB | 211 MiB | 권장 |
| 1024 × 2(ORM 제거, Albedo 에 굽기) | 48 MiB | 240 MiB | 비권장(채널 손실) |

즉 실내를 절반으로 줄이면 **216 MiB(예산의 2.1%)** 를 회수한다. 차량 예산이 이미 14%라 절실하지는 않지만, 실내를 4096 으로 올리고 싶을 때(144 MiB/차종) 이 여유가 그 결정을 가능하게 한다.

---

## 18. RTX 3080 10 GiB 예산표

차량 텍스처만 계산하면 "14%니까 괜찮다"로 끝난다. 실제로는 같은 VRAM 에 프레임버퍼·지오메트리·환경·그림자가 함께 산다. 아래는 **계획용 분배**이고, 실측은 각 줄의 방법으로 확인한다.

| 항목 | 4K/60 목표 (MiB) | 내용 | 실측 방법 |
| --- | --- | --- | --- |
| 프레임버퍼·포스트 | 1,800~2,500 | 4K 컬러+HDR+TSR 히스토리+톤매핑 | `stat rhi` 의 render target |
| 지오메트리(Nanite·인스턴스) | 700~1,200 | 108 메시 + 2,000 인스턴스(0.5 MiB) + 클러스터 페이지 | `stat rhi`, `stat nanite` |
| 텍스처 상주(차량 + 환경) | 2,940~3,940 | 차량 **1,440**(18 차종 × 80 MiB) + 환경 1,500~2,500 | 13장 계산, `stat streaming` |
| Lumen·VSM·그림자 | 800~1,500 | 카드·프로브·섀도우 페이지 | `stat lumen`, `r.Shadow` |
| Slate·UI·기타 | 200~400 | 폰트·UI 아틀라스 | `stat rhi` |
| **상주 합계** | **약 6,400~9,500** | 10 GiB = 10,240 MiB | — |
| (그릇) 스트리밍 풀 | 1,024~1,536 | 위 텍스처가 실제로 상주하는 한도 — **합계에 더하지 않는다** | `r.Streaming.PoolSize` |

스트리밍 풀은 "텍스처가 들어가는 그릇"이므로 텍스처 상주량과 따로 더하면 이중 계산이 된다. 표에서 풀은 상주 합계에 넣지 않고, **상주 상한을 정하는 값**으로만 둔다.

상주 합계의 상한(9,500 MiB)이 10 GiB 에 가깝다. 텍스처 상주를 3,940 MiB 로 잡으면 풀 1,536 MiB 보다 크므로, 실제로는 **모든 텍스처를 동시에 상주시킬 수 없고 밉 스트리밍이 일어난다** — 이것이 정상이다. 판단 기준은 "모두 상주하는가"가 아니라 "가장 가까운 차량이 밉 0단을 유지하는가"다. 차량 쪽에서 확인해야 할 것은 다음 셋이다.

1. **스트리밍 풀이 차량을 감당하는가**: 1,440 MiB 를 모두 상주시키려면 풀이 1,024 이면 부족하다. 그러나 실제로는 근접 차량 몇 대만 밉 0단이 필요하므로, **풀 1,024 에서도 차량 화질이 유지되는지** 2,000대 배치 지도에서 확인한다(도심 4차선 100 m 구간이 최악).
2. **그림자가 차량 때문에 터지지 않는가**: 2,000대 그림자는 VSM 페이지를 압박한다. 60 m 그림자 컬링 + 40 m 밖 캐스케이드 제외.
3. **Lumen 카드**: 차량 2,000대의 Lumen 표면 카드는 별도 메모리를 쓴다. 실내가 있는 차량은 카드 메모리가 커지므로, 원거리 차량은 카드 생성을 끈다.

이 표를 팀 예산 문서로 쓰려면 각 줄을 **실측값으로 교체**해야 한다. 측정 순서는 빈 맵 → 108 메시만 → 2,000대 배치 → 환경 추가 순으로, 각 단계에서 `stat rhi`·`stat streaming` 을 기록한다.

---

## 19. 계산기 사용법

`pipeline/vehicle_asset_optimizer.py` 는 표준 라이브러리만 쓴다. 블렌더·엔진 없이 돈다.

```bash
python -m pipeline.vehicle_asset_optimizer formats
python -m pipeline.vehicle_asset_optimizer vram --chassis 18 --exterior 4096 --interior 2048
python -m pipeline.vehicle_asset_optimizer vram --chassis 40 --exterior 4096 --interior 2048 --budget-mib 10240
python -m pipeline.vehicle_asset_optimizer vram --exterior-maps "normal=bc5,albedo=bc7,orm=bc7:3" --json
python -m pipeline.vehicle_asset_optimizer packing --resolution 4096 --separate-fmt bc4
python -m pipeline.vehicle_asset_optimizer explode --demo --axis z --gap 0.02 --unit mm
python -m pipeline.vehicle_asset_optimizer explode --json scene.json --axis y --gap 0.01 --dump-json
python -m pipeline.vehicle_asset_optimizer cage --json cage.json --min-margin 0.004
python -m pipeline.vehicle_asset_optimizer checklist
```

| 명령 | 계산하는 것 | 문서 |
| --- | --- | --- |
| `formats` | BC 포맷별 bpp 와 4096/2048/1024 실크기(밉 포함) | 12장 |
| `vram` | 차종당·전체 텍스처 상주량, 예산 비율, 판정, 절감 시나리오, 인스턴스 버퍼 | 13·15장 |
| `packing` | 분리 저장 vs ORM 절감률(포맷 조합별) | 14장 |
| `explode` | 겹치는 부품의 축 방향 오프셋, 잔여 겹침 검사 | 9.3 |
| `cage` | 케이지 토폴로지·감싸기·여유·실루엣 검사 | 10.5 |
| `checklist` | 12단계 체크리스트 | 20장 |

### 19.1 케이지 JSON 형식

```json
{
  "low":  {"name": "door_Low",  "lo": [-0.60, 0.00, 0.10], "hi": [0.60, 0.08, 0.70], "verts": 1840},
  "high": {"name": "door_High", "lo": [-0.60, -0.01, 0.10], "hi": [0.60, 0.10, 0.70], "verts": 412000},
  "cage": {"name": "door_Cage", "lo": [-0.612, -0.018, 0.092], "hi": [0.612, 0.116, 0.708], "verts": 1840}
}
```

블렌더에서 이 JSON 을 만드는 것은 9.3 의 `dump_bounds` 로 충분하다(케이지·하이폴리도 같은 함수로 덤프).

### 19.2 판정 기준

| 판정 | 예산 비율 | 의미 |
| --- | --- | --- |
| 여유 | ≤ 20% | 차량이 다른 항목을 압박하지 않는다 |
| 적정 | 20~35% | 관리 가능. 18장 예산표로 나머지를 확인 |
| 주의 | 35~50% | 다른 항목을 줄이거나 해상도를 낮춘다 |
| 초과 | > 50% | 10 GiB 에서는 성립하지 않는다 |

---

## 20. 블렌더 12단계 익스포트·베이크 체크리스트

각 단계는 **건너뛰면 반드시 나중에 비용이 발생**한다. 괄호는 담당 장.

| # | 단계 | 확인 사항 | 실패 시 증상 |
| --- | --- | --- | --- |
| 1 | LP 생성 | `IsLowPoly` 스위치가 실제로 적용됐는가(함수 반환값 확인), 삼각형 ≤ 예산 (2·7장) | LP 가 HP 그대로 → 베이크 시간 폭발 |
| 2 | 실루엣 비교 | 3면 실루엣 오차 ≤ 표의 값, 패널 라인 위치 우선 (3.2) | 원거리에서 차체가 각져 보임 |
| 3 | 법선 전송 | Decimate **후** Data Transfer, `POLYINTERP_NEAREST`, 4.1+ 는 auto smooth 불필요 (5장) | 하이라이트 흐름·이중 적용 |
| 4 | UV | 클러스터당 1 세트(0~1), 패딩 8 px(4096)/4 px(2048), 겹침 ≤ 5% (3.4) | 텍스처 늘어남·이음 |
| 5 | 법선 확인 | 뒤집힌 면 0, 하드 엣지가 패널 라인과 일치 (4.4) | 검은 점·각진 띠 |
| 6 | 익스플로전 | 겹치는 부품 축 분리, 이동 전 위치 JSON 저장, 잔여 겹침 0 (9.3~9.4) | 이웃 부품 무늬 |
| 7 | 케이지 | LP 복제 + `Alt+S`(Offset Even), 여유 0.4~35%, verts 동일 (10.2·10.5) | 마젠타 구멍 |
| 8 | 베이킹 | Normal(탄젠트, G=-Y) + AO + ORM, 마진 8 px, 512~1024 샘플 (9.5) | 전반적 품질 저하 |
| 9 | 검증 | 4K 1:1 에서 마젠타·검정 픽셀 수, 그라디언트 끊김 (9.2·11.6) | 엔진에서 발견 |
| 10 | 복원 | 오프셋 0, 좌표 차이 < 1e-6, 원점·스케일 유지 (9.4) | 조립 기준점 틀어짐 |
| 11 | 삼각화 | Triangulate Apply, `Keep Custom Normals` ON, 삼각형 수 재기록 (11.2) | 대각선 이음 |
| 12 | 익스포트 | **3c**: Color 미전송 / Recompute Normals 끔 / Tangent 재계산 끔 (11.5) | 노멀맵 기울어짐 |

```bash
python -m pipeline.vehicle_asset_optimizer checklist
```

---

## 21. 트러블슈팅 매트릭스

증상에서 원인으로 가는 표. 왼쪽 위에서부터 확인한다.

| 증상 | 1순위 원인 | 2순위 | 확인 방법 | 수정 |
| --- | --- | --- | --- | --- |
| 노멀맵에 마젠타 점 | 케이지 없음/여유 부족 (10장) | Ray Distance 부족 | `cage` 검사, 여유 < 0.4% | `Alt+S` 한 번 더, 케이지 사용 |
| 마젠타가 홈 안쪽에만 | 케이지 자기 교차 (10.4) | 홈 안쪽 버텍스 과다 부풀림 | 케이지 self-overlap | 홈 버텍스 가중치 0 |
| 이웃 부품 무늬가 찍힘 | 겹판 (9장) | 케이지 과대 | `explode` 잔여 겹침, 케이지 여유 > 35% | 익스플로전, 케이지 축소 |
| 판이 두 겹으로 보임 | 두께 0 판 (9.1) | 안쪽 면(뒤판) 포함 | 두께 측정 | Solidify 1 mm, 뒤판 제외 |
| 대각선 이음 | 삼각화 미적용 (11.2) | 커스텀 노멀 재계산 | 삼각화 전후 비교 | Triangulate Apply + Recompute 끔 |
| 하이라이트가 기울어짐 | 노멀 전송 순서 (5.3) | Impoter 노멀 재계산 | 11.6 평면 노멀 테스트 | 전송 → 베이크 순서, Import Normals and Tangents |
| 좌우가 비대칭 | 미러 UV·음수 스케일 (11.1) | 비대칭 실루엣 | 미러 면 UV 확인 | UV 별도 섬, 스케일 Apply |
| 요철이 반대로 보임 | G 채널 규약 (11.1) | 노멀 스위즐 | 11.6 그라디언트 | G=-Y 베이크 또는 Flip Green |
| 패널 라인이 흐릿함 | LP 하드 엣지 소실 (5장) | 베벨 과다 | 와이어프레임 | 커스텀 노멀 재전송, 베벨 1단 |
| 전체가 밋밋함 | LP 가 HP 에서 떨어짐 (4장) | Shrinkwrap 미적용 | 4.4 최대 변위 | Shrinkwrap + 가중치 |
| 실루엣이 물결침 | Shrinkwrap 전면 적용 (4.1) | Decimate 비율 과다 | 실루엣 3면 | 경계 가중치 0, Planar 우선 |
| 텍스처가 뭉개짐 | 스트리밍 풀 초과 (16장) | 밉 바이어스 | `stat streaming` | 풀 1,024~1,536, 그룹 바이어스 |
| 프레임 드랍(2,000대) | 그림자·VSM (15.2) | LOD 미전환 | `stat gpu`, `stat shadowrendering` | 60 m 그림자 컬링, 실내 LOD |
| VRAM 초과 | 환경 텍스처 (18장) | 차량 해상도 | `stat rhi`, 예산표 | 18장 표로 항목별 축소 |
| 차가 100배로 들어옴 | Apply Unit/Convert Scene Unit (11.4) | 스케일 Apply 누락 | 100 cm 테스트 큐브 | 익스포트·임포트 단위 통일 |
| 재질이 이중으로 어두움 | 버텍스 컬러 전송 (11.5 ①) | AO 두 번 곱 | 머티리얼·버텍스 컬러 확인 | Color 미전송, AO 경로 하나만 |
| 베이크가 너무 느림 | 케이지 과대·LP 과밀 (9.5) | 샘플 과다 | 클러스터별 소요 시간 | 해상도 분리, 케이지 축소, 256 샘플 |

---

## 22. 엔진 임포트 필수 세팅

| 분류 | 항목 | 값 | 이유 |
| --- | --- | --- | --- |
| 메시 | Normal Import Method | Import Normals and Tangents | 베이크한 탄젠트 베이스 유지 |
| 메시 | Normal Generation Method | MikkTSpace | 재계산 시에도 표준 기준 |
| 메시 | Compute Weighted Normals | OFF | 커스텀 노멀 보존 |
| 메시 | Import Mesh LODs | ON | 클러스터별 LOD |
| 메시 | Transform Vertex to Absolute | OFF | 원점 유지 |
| 메시 | Convert Scene / Scene Unit | ON / ON | m → cm 변환 |
| 빌드 | Recompute Normals | OFF | 3c ② |
| 빌드 | Recompute Tangents | OFF | 3c ③ |
| 빌드 | Use MikkTSpace Tangent Space | ON | 재계산 시 기준 |
| 텍스처 | Normal (BC5) | sRGB OFF | 데이터 |
| 텍스처 | ORM (BC7) | sRGB OFF | 데이터 |
| 텍스처 | Albedo (BC7) | sRGB ON | 색 |
| 텍스처 | Compression | 기본(BC) + Normal map = BC5 | 자동 선택을 신뢰하되, 차량 그룹은 고정 |
| 텍스처 | Mip Gen Settings | `FromTextureGroup` | 그룹 바이어스로 관리 |
| 텍스처 그룹 | `TEXTUREGROUP_Vehicle` | 커스텀 등록 | 차량만 따로 LOD 바이어스 |
| 머티리얼 | Tangent Space Normal | ON | 노멀맵 슬롯 |
| 머티리얼 | Flip Green Channel | 베이크 규약과 반대일 때만 | G 채널 |

---

## 23. 참고 자료

**블렌더**

- [Render Baking — Blender Manual](https://docs.blender.org/manual/en/latest/render/cycles/baking.html) — `Selected to Active`, `Cage`, `Cage Object`, `Cage Extrusion`, `Max Ray Distance`. "Ray distance is only available when not using Cage" 명시
- [BakeSettings (Blender Python API)](https://docs.blender.org/api/current/bpy.types.BakeSettings.html) — `use_cage`, `cage_object`, `cage_extrusion`, `max_ray_distance`, `normal_space`
- 이 저장소: [docs/blender_pipeline.md](blender_pipeline.md) — 감면 의사결정(경로 A/B), Decimate·Quadriflow, UV·케이지, Cycles 베이킹
- 이 저장소: [pipeline/blender_import.py](../pipeline/blender_import.py) — 감면·UV·케이지·베이킹 자동화 스크립트

**탄젠트·노멀**

- MikkTSpace: Morten S. Mikkelsen 의 탄젠트 공간 표준. 블렌더·UE5 모두 이 계열 구현을 쓴다
- [UE: FbxMeshImportData (Python API)](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/FbxMeshImportData) — `normal_import_method`, `normal_generation_method`, `compute_weighted_normals`

**압축 포맷**

- [Block Compression (Direct3D 10)](https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression) — BC1~BC5 블록당 바이트
- [Texture Block Compression in Direct3D 11](https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11) — BC6H/BC7 블록당 16 B
- [BC7 Format](https://learn.microsoft.com/en-us/windows/win32/direct3d11/bc7-format) — 4×4 텍셀 / 16 B 고정

**엔진·메모리**

- 이 저장소: [pipeline/texture_packer.py](../pipeline/texture_packer.py) — ORM 패킹과 채널 통계 검증
- 이 저장소: [docs/pbr_material_pipeline.md](pbr_material_pipeline.md) — 채널 패킹 원리, 색공간, UE 머티리얼
- 이 저장소: [docs/open_world_content_and_architecture_guide.md](open_world_content_and_architecture_guide.md) — Chaos Vehicles, 탈것 네트워크, 대량 배치

**이 문서의 도구**

- [`pipeline/vehicle_asset_optimizer.py`](../pipeline/vehicle_asset_optimizer.py) — `formats` / `vram` / `packing` / `explode` / `cage` / `checklist`
- [`tests/test_vehicle_asset_optimizer.py`](../tests/test_vehicle_asset_optimizer.py) — 109개 테스트(포맷 크기, 밉 체인, 함대 예산, ORM 절감률, 익스플로전 분리, 케이지 검증, CLI, 문서 정합)

---

> **한 줄 요약**: 절차 생성 차량의 실패는 (1) LP 에서 경계를 지키고, (2) 베이크에서 광선의 시작점(케이지)과 탄젠트의 기준(3c)을 고정하고, (3) 텍스처를 차종 수로만 곱해 계산하면 막을 수 있다. 18 차종 × 80 MiB = 1,440 MiB 는 10 GiB 의 14% 이고, 2,000대의 인스턴스 데이터는 0.5 MiB 다. **예산은 텍스처에서 오지, 대수에서 오지 않는다.**
