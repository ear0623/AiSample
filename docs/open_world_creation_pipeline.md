# 오픈월드 제작 파이프라인: 공간 · 지형 · 스트리밍 · PCG · 라이팅 · 최적화

> 대상: C++/그래픽스 배경으로 UE5에서 오픈월드를 직접 만드는 개발자
> 범위: 월드 규모와 좌표계 설계 → 지형 생성·임포트 → 월드 파티션 스트리밍 → PCG/식생 → 도로·수계 → 대기·라이팅 → HLOD·프로파일링 → 단계별 로드맵
> 기준 시점: **2026-11. Unreal Engine 5.8**(2026-06-17 출시, UE5의 마지막 계획된 메이저 릴리스) 기준.
> 5.7/5.8에서 실험(Experimental)로 표기된 기능은 본문에 그렇게 명시했다. 실험 기능은 프로덕션 리스크로 계산에 넣어야 한다.
> 함께 쓰는 파일: [`pipeline/open_world_helper.py`](../pipeline/open_world_helper.py) · [`tests/test_open_world_helper.py`](../tests/test_open_world_helper.py)

---

## 목차

0. [한눈에: 오픈월드는 기능이 아니라 예산이다](#0-한눈에-오픈월드는-기능이-아니라-예산이다)
1. [코어 아키텍처와 공간 관리](#1-코어-아키텍처와-공간-관리)
2. [지형 생성과 지형 조형](#2-지형-생성과-지형-조형)
3. [월드 스트리밍과 공간 분할](#3-월드-스트리밍과-공간-분할)
4. [PCG와 식생](#4-pcg와-식생)
5. [인프라: 도로와 수계](#5-인프라-도로와-수계)
6. [대기·하늘·라이팅](#6-대기하늘라이팅)
7. [렌더링 최적화와 프로파일링](#7-렌더링-최적화와-프로파일링)
8. [단계별 제작 로드맵](#8-단계별-제작-로드맵)
9. [계산기와 체크리스트 사용법](#9-계산기와-체크리스트-사용법)
10. [자주 터지는 지점](#10-자주-터지는-지점)
11. [참고 자료](#11-참고-자료)

---

## 0. 한눈에: 오픈월드는 기능이 아니라 예산이다

오픈월드 제작이 어려운 이유는 기능이 많아서가 아니다. **같은 예산(프레임 16.6 ms, VRAM 8~10 GB, 스트리밍 대역폭, 빌드 시간)을 수십 km²에 나눠 써야 하기 때문**이다. 그래서 오픈월드 파이프라인은 다음 순서로 정리된다.

```
[규모와 예산]  월드 크기, 이동 수단, 타깃 기기, 프레임/메모리 예산
      │
      ▼
[공간 구조]    좌표계(LWC) → 런타임 그리드(셀/로딩 반경) → 데이터 레이어 → HLOD 레이어
      │
      ▼
[지형]         외부 DCC 침식 시뮬레이션 → 16-bit 하이트맵 → Landscape → RVT 머티리얼
      │
      ▼
[표면·배치]    바이옴 마스크 → PCG 그래프 → HISM/Nanite Foliage → 수동 아트 디렉팅
      │
      ▼
[인프라]       스플라인 도로·강 → 랜드스케이프 디폼 → Water Body → 부력/게임플레이
      │
      ▼
[빛·대기]      Sky Atmosphere → Volumetric Cloud → Lumen → VSM → 시간대 순환
      │
      ▼
[검증]         HLOD 빌드 → 쿡 → 프로파일링(Insights/Spatial Profiler) → 회귀
```

핵심 원칙 네 가지:

1. **숫자로 먼저 정하고, 콘텐츠로 나중에 채운다.** 셀 크기·로딩 반경·텍셀 밀도·HLOD 셀은 아트가 아니라 수치 설계다. 9장의 계산기로 착수 전에 확정한다.
2. **스트리밍 단위와 제작 단위를 일치시킨다.** 한 셀에 300 MB가 들어가면 어떤 로딩 반경도 구제하지 못한다. 셀당 예산을 정하고, 그 예산을 넘는 POI는 쪼갠다.
3. **원경은 원경용 표현으로만 그린다.** HLOD 프록시, Lumen Far Field, 임포스터, voxel. 원본 지오메트리를 멀리서도 유지하는 선택은 오픈월드에서 거의 항상 진다.
4. **실험 기능은 일정 리스크로 계산한다.** 5.8 기준 Mesh Terrain, Nanite Foliage, Water, Virtual Heightfield Mesh, Fast Geometry Streaming은 모두 Experimental이다. 코어 경로에 넣으려면 대체 경로를 함께 설계한다.

### 예산 예시 (절대 기준이 아니라 작성 양식)

| 항목 | 예시 값 (PS5/XSX, 60 fps, 1440p→4K TSR) | 비고 |
| --- | --- | --- |
| 프레임 | 16.6 ms | 60 fps |
| GPU 합계 | 14.5 ms (여유 2 ms) | |
| ├ Nanite/베이스 패스 | 4.0 ms | 오파크 지오메트리 |
| ├ Lumen GI + Reflections | 3.5 ms | High 스케일러빌리티 |
| ├ 가상 섀도우 맵 | 2.5 ms | 방향광 + 로컬 |
| ├ 대기/구름/안개 | 1.5 ms | |
| ├ 포스트/TSR | 2.0 ms | |
| └ 기타(물, 파티클, UI) | 1.0 ms | |
| 스트리밍 상주 | 셀 45개 × 25 MB ≈ 1.1 GB | 월드 8 km, 256 m 셀 |
| 텍스처/VT 풀 | 3.5 GB | 기기 프로파일별 |
| 셀 1개 로드 | 100초 이내(도보), 20초 이내(차량 30 m/s) | 로딩 윈도우 |

이 표를 프로젝트 시작 시 채우고, 모든 기능 추가는 이 표에서 한 줄을 빼거나 다른 줄을 줄이는 거래로 취급한다.

---

## 1. 코어 아키텍처와 공간 관리

### 1.1 대규모 좌표계(Large World Coordinates)

#### 왜 32-bit float로는 안 되는가

float32는 유효 자릿수 약 7자리다. 언리얼은 1 uu = 1 cm이므로, 원점에서 멀어질수록 표현 가능한 최소 간격(ULP)이 커진다.

| 원점에서 거리 | float32의 최소 간격 |
| --- | --- |
| 10 km | 약 1 mm |
| 100 km | 약 8 mm |
| 1,000 km | 약 6 cm |
| 8,389 km | 1 m |
| 384,400 km(지구–달) | 약 32 m |

UE4의 월드 한계는 2,097,152 uu ≈ **21 km**였다. 그 밖에서는 버텍스가 양자화되어 카메라가 떨리고, 물리가 튀고, 스켈레톤이 늘어난다.

#### UE5의 해법

- **월드 한계**: 2^43 cm ≈ **8,800만 km**. 지구–태양 거리(1 AU, 1.496억 km)의 약 60%로, 행성 하나를 1:1로 담을 수 있는 규모다.
- **CPU**: 핵심 수학 타입(FVector 등)이 double 기반. 블루프린트의 Float도 double이다. C++에서 `float`로 선언한 `UPROPERTY`는 그대로 32-bit이므로, 좌표를 다루는 코드는 `double`/`FVector`(UE5의 FVector는 double)를 써야 한다.
- **GPU**: double을 쓰지 않는다. 레지스터·대역폭·명령 비용이 2배 이상이 되고, GPU 벤더의 우선순위도 아니다. 대신 두 가지를 쓴다.
  - **Translated world space(카메라 상대 좌표)**: 렌더링 직전에 월드를 카메라 기준으로 평행 이동해 float로 처리한다. 카메라 근처는 오차가 작고, 먼 곳은 화면상 작게 보이므로 오차가 덜 보인다.
  - **Double-float(DF)**: double 값을 high float와 low float 두 개로 나눠 전달한다. UE5는 월드 크기 2^43 안에서 두 점이 10 km 이내면 이 연산의 오차가 1/16 cm 미만이라고 설명한다.
- **예외**: Niagara 파티클 등 일부 시스템은 여전히 단정밀 + 그리드 셀 조합으로 좌표를 저장한다. 서드파티 플러그인과 자체 셰이더도 월드 좌표를 float로 받는 곳이 있다.

#### 실무 규칙

1. 플레이 영역을 원점에서 멀리 두지 않는다. 가능하면 월드 중심을 원점에 맞추고, 텔레포트·시네마틱에서 좌표 점프를 명시적으로 처리한다. (5 km만 벗어나도 정밀도 문제가 관측된 사례가 있다.)
2. 월드 좌표를 머티리얼/WPO에서 직접 크게 스케일해 쓰지 않는다. RVT는 월드 좌표 → UV 변환을 쓰므로, 원점에서 먼 곳의 RVT 샘플링이 흐려질 수 있다. RVT 볼륨을 나누거나 카메라 상대 좌표를 쓴다.
3. 물리·내비게이션·오디오처럼 double을 지원하지 않는 하위 시스템의 좌표 한계를 문서화한다.
4. 88M km는 "무한"이 아니다. 행성 규모라면 유닛 스케일을 바꾸거나(1 uu = 1 m) 월드를 나눈다.

### 1.2 월드의 분할 단위

UE5 오픈월드의 데이터 계층은 다음과 같다.

| 계층 | 단위 | 역할 |
| --- | --- | --- |
| World | Persistent Level 1개 | 전체 월드. 서브레벨을 수동으로 나누지 않는다. |
| Runtime Grid | Cell (예: 256 m) | 거리 기반 로드/언로드의 단위 |
| Actor | OFPA 파일 1개 | 액터 단위 저장·체크아웃·로드 |
| Data Layer | 이름 붙은 논리 집합 | 낮/밤, 퀘스트, 파괴 상태, 계절 |
| HLOD Layer | 별도 그리드 | 언로드된 셀의 원경 대체물 |
| Level Instance | 묶음 | 반복 구조물의 재사용 단위 |

이 계층들이 서로 **다른 주기**로 움직인다는 점이 중요하다. 셀은 플레이어 이동에 따라, 데이터 레이어는 게임 상태에 따라, HLOD는 빌드 시점에, OFPA는 소스 컨트롤 단위로 움직인다. 이 주기가 어긋나면 "HLOD는 있는데 데이터 레이어가 꺼져 있어 프록시만 남는" 식의 버그가 난다.

### 1.3 비동기 로딩 구조

셀 하나가 로드되는 경로:

```
Streaming Source(플레이어) 위치 갱신
   → Runtime Hash가 반경 내 셀 집합 계산
   → 셀 상태: Unloaded → Loading → Loaded → Activated
   → 비동기 로드(IO → 역직렬화 → 액터 등록)
   → (Data Layer 조건 충족 시) 활성화
   → 렌더/물리/내비게이션 반영
```

여기서 시간을 잡아먹는 것은 디스크 읽기만이 아니다.

- **역직렬화와 액터 등록**: 셀당 액터 수가 많을수록 게임 스레드가 길어진다.
- **텍스처/메시 스트리밍**: 셀 로드와 별개로 밉이 도착해야 화면이 완성된다.
- **GC**: 셀이 언로드되면 액터가 대기 상태가 되고, GC가 몰리면 히치가 된다. 5.8에는 언로드 대기 액터 수 기준으로 GC를 돌리는 옵션이 추가됐다(`s.ContinuouslyIncrementalGCWhileActorsPendingPurge`, `wp.Runtime.LevelStreamingContinuouslyIncrementalGCWhileActorsPendingPurgeForWP`).
- **PSO/셰이더 컴파일**: 새 머티리얼이 처음 보일 때. 쿡 단계 PSO 캐시로 상쇄한다.
- **물리/내비메시 타일 빌드**: 셀 경계에서 런타임 내비 타일이 재생성되면 프레임이 튄다.

5.8 기준 **Fast Geometry Streaming**은 이 경로를 분리한다. 게임플레이와 무관한 정적 지오메트리(바위, 잔해, 장식)를 스트리밍 히치 없이 빠르게 올리는 플러그인으로, 5.8에서 데칼과 점/스포트/렉트 라이트 컴포넌트까지 지원이 늘었다. 2026-11 기준 여전히 Experimental이므로, 코어 월드가 아니라 "히치를 줄이는 보조 경로"로 검증 후 채택한다.

### 1.4 규모 결정: 셀·로딩 반경·스트리밍 처리량

#### 기본 공식

- 그리드 셀 수 = ceil(월드 크기 / 셀 크기)²
- 동시 로드 셀 수 = 반경 R 안에 일부라도 걸치는 셀 수 (정사각형 (2R/c+1)²가 아니라 모서리가 빠진 원형)
- 셀 통과 시간 = 셀 크기 / 이동 속도
- 로딩 윈도우 = (R − c/2) / 이동 속도
- 필요 처리량 = 셀당 데이터량 / 로딩 윈도우
- 상주 메모리 ≈ 동시 로드 셀 수 × 셀당 데이터량

#### 예: 8 km × 8 km, 256 m 셀, 768 m 반경

```
셀          32 × 32 = 1,024
동시 로드   45개 (7×7=49에서 모서리 4개 제외)
셀 통과     42.7초 (도보 6 m/s)
로딩 윈도우 106.7초
셀당 30 MB → 필요 처리량 0.3 MB/s, 상주 1.29 GB
```

#### 셀 크기 선택표

| 셀 크기 | 장점 | 단점 | 어울리는 경우 |
| --- | --- | --- | --- |
| 128 m | 메모리 피크 작음, 세밀한 컬링 | 셀 경계 빈번, IO/등록 오버헤드 큼 | 도보 중심, 실내 밀집, 고밀도 도시 |
| 256 m | 균형. Epic 예시 기본값 | 고속 이동 시 로딩이 쫓김 | 일반 오픈월드 |
| 512 m | IO 횟수 적음, 원경 유지 쉬움 | 셀당 메모리 큼, 언로드 단위 굵음 | 차량/비행, 밀도 낮은 자연 |
| 1024 m+ | 스트리밍 단순 | 메모리 폭발, 히치 시 복구 불가 | 사실상 정적 배경, 컷신 전용 |

로딩 반경은 보통 **셀의 2~4배**로 잡는다. 768 m는 256 m 셀의 3배로, 3셀 반경 안의 콘텐츠가 화면에 들어오기 전에 로드된다는 뜻이다. 이동 수단이 빠를수록 반경을 키우기보다 **셀을 키우고 데이터를 줄이는** 쪽이 안정적이다. 반경을 키우면 상주 셀 수가 제곱으로 늘어난다.

> 계산은 9장의 `grid` 명령으로 바로 뽑는다. 직사각형 월드는 X/Y를 따로 계산해 큰 쪽을 기준으로 예산을 잡는다.

---

## 2. 지형 생성과 지형 조형

### 2.1 외부 DCC에서의 지형 제작

언리얼의 Landscape는 2.5D 하이트필드다. 지질학적 설득력(산맥, 유역, 침식)은 엔진 안에서 만들기 어렵고, 보통 외부 DCC에서 시뮬레이션한 뒤 하이트맵으로 가져온다.

| 도구 | 강점 | 약점 | 파이프라인 |
| --- | --- | --- | --- |
| **Houdini**(HeightField + Houdini Engine) | 완전 절차적. 침식·유역·도로·마스크를 한 그래프로. HDA로 UE에 직접 Landscape 생성 | 학습 곡선, 라이선스 비용, HDA 쿡 시간 | HeightField Tile Split → Houdini Engine이 Landscape/타일 생성. 마스크는 레이어로 자동 변환 |
| **World Machine** | 빠른 침식·디테일, 가벼움, 타일 빌드 | 절차 그래프 유연성 낮음, 대규모 파이프라인 통합 제한 | Tiled Build → r16 타일 → Landscape Import |
| **Gaea 2** | 아트 친화적 UI, 침식 품질, 빠른 반복 | 파이프라인 자동화·버전 관리 약함 | 고해상도 익스포트 → 타일 분할 → Import |
| **UE Landscape 도구** | 즉시 반복, 스컬프트/페인트 | 대규모 침식 불가, 디테일 한계 | 회색박스/수정용. 최종 지형은 DCC |

#### 침식 시뮬레이션의 종류와 역할

- **수력 침식(Hydraulic)**: 강우가 만든 유수와 퇴적. 계곡·선상지·삼각주를 만든다. droplet 방식(입자 굴리기)과 grid 방식이 있다.
- **열 침식(Thermal)**: 경사가 안식각을 넘으면 물질이 미끄러진다. 절벽 아래 테일러스(talus)를 만든다.
- **해안/파랑 침식**: 파도 방향과 해수면 기준으로 절벽·해식동굴.
- **디브리 플로우(Debris flow)**: 산사태성 퇴적. 급경사 협곡 하부에 팬을 만든다.
- **멀티스케일**: 대륙 규모 fBm/도메인 워프 → 지역 규모 침식 → 국소 디테일(바위, 계곡선). 한 번의 침식으로 모든 스케일을 얻으려 하면 지형이 밋밋해진다.

실무 순서는 보통 이렇다.

1. **매크로 실루엣**: 산맥 능선, 분지, 해안선을 스케치(스플라인/마스크/노이즈).
2. **유역과 배수**: Flow accumulation으로 강이 흐를 경로를 먼저 정한다. 강은 지형보다 나중에 그리면 항상 어색하다.
3. **침식**: 수력 → 열 → 디브리를 순차 적용. 각 단계의 마스크를 저장한다.
4. **퇴적/평탄화**: 호수면, 범람원, 도로/정착지 후보지를 평탄화한다.
5. **레이어 마스크 익스포트**: 경사, 고도, 유속, 퇴적량, 바이옴을 8-bit 마스크로 함께 내보낸다. 이 마스크가 4장 PCG와 2.4 머티리얼의 입력이 된다.

### 2.2 하이트맵 규격과 익스포트

#### Landscape의 구조와 제약

- 하이트 데이터는 컴포넌트마다 텍스처 1장(16-bit)에 저장된다.
- 컴포넌트의 하이트 데이터(정점 수)는 2의 거듭제곱이어야 하고, **섹션은 최대 256 버텍스**.
- 섹션은 컴포넌트당 1개 또는 4개(2×2). 섹션은 LOD 계산의 단위이고, **섹션 하나가 드로우콜 하나**다.
- 따라서 전체 정점 수 = 컴포넌트 수 × 컴포넌트당 쿼드 + 1.

Epic 권장 크기(최대 면적, 최소 컴포넌트):

| 전체 정점 | 섹션당 쿼드 | 섹션/컴포넌트 | 컴포넌트 크기 | 총 컴포넌트 | 드로우콜(섹션) |
| --- | --- | --- | --- | --- | --- |
| 127 | 63 | 2×2 | 126 | 1 | 4 |
| 253 | 63 | 2×2 | 126 | 4 | 16 |
| 505 | 63 | 2×2 | 126 | 16 | 64 |
| 1,009 | 63 | 2×2 | 126 | 64 | 256 |
| 2,017 | 63 | 2×2 | 126 | 256 | 1,024 |
| 4,033 | 63 | 2×2 | 126 | 1,024 | 4,096 |
| 8,129 | 127 | 2×2 | 254 | 1,024 | 4,096 |

Epic은 대규모 Landscape에서 **컴포넌트 1,024개**를 상한으로 권장한다. 4,033과 8,129가 모두 1,024개인 이유는 8,129에서 섹션을 127 쿼드로 키워 컴포넌트를 254 쿼드로 만들기 때문이다.

#### Z 스케일과 높이 정밀도

Landscape는 높이를 −256 ~ 255.992 범위의 16-bit로 저장하고, 임포트 시 Z scale을 곱한다.

```
Z scale = 원하는 높이 범위(m) × 100 / 512
```

- 기본 Z scale 100 → 실제 높이 범위 512 m (−256 ~ +256 m).
- 예: 높이 범위 2,000 m를 표현하려면 Z scale = 2000 × 100 / 512 = 390.6.
- 16-bit의 정밀도는 512 m / 65,536 ≈ **0.78 cm**(전 범위 사용 시). 높이 범위를 키우면 정밀도도 비례해 나빠진다.

Houdini Engine은 기본적으로 16-bit 범위의 **3/4만** 사용해 이후 스컬프트 여유를 남긴다. 이 경우 4 km 높이 지형의 Z 정밀도는 약 **8.13 cm**, 전 범위를 쓰면 **6.10 cm**다. 헬퍼의 `landscape` 명령이 두 경우를 모두 계산한다.

#### 파일 포맷과 타일

- 지원: 16-bit grayscale PNG, 16-bit r16, 8-bit r8, `.raw`(+동일 이름 `.json`에 width/height/bit depth).
- **타일 분할**: 8 km를 한 장으로 만들 수 없을 때(권장 최대 8,129 정점) 타일로 나눈다. 인접 타일은 경계 정점을 공유해야 하고, Houdini의 Heightfield Tile Split은 lower/upper overlap으로 이를 맞춘다. World Partition 레벨에서는 `unreal_landscape_partition_grid_size` 속성으로 파티션 그리드를 지정한다.
- **타일을 나누면**: 각 타일이 별도 Landscape Actor가 되어 컴포넌트·드로우콜이 배로 늘고, 경계 심·LOD 불연속·RVT 경계 문제가 생긴다. 가능하면 **한 장 8,129가 낫고**, 더 큰 월드는 타일 수를 최소화한다.

#### 임포트 체크리스트

- [ ] 정점 수가 권장 크기 중 하나인가 (127/253/505/1009/2017/4033/8129)
- [ ] 섹션/컴포넌트 설정이 정점 수와 나누어떨어지는가
- [ ] Z scale이 목표 높이 범위와 맞는가 (해수면 기준 오프셋 포함)
- [ ] 높이 정밀도가 목표(보통 1~10 cm) 안인가
- [ ] 마스크 레이어가 함께 임포트됐고 가중치가 정규화됐는가
- [ ] 타일 경계 정점이 일치하는가
- [ ] 콜리전이 생성됐고 경사 한계가 게임플레이와 맞는가

### 2.3 Landscape 머티리얼: 레이어 스택과 자동 블렌딩

랜드스케이프 머티리얼의 비용은 **레이어 수 × 텍스처 샘플 수**에 비례한다. 12개 레이어를 한 머티리얼에서 전부 샘플링하면 지형 픽셀마다 수십 번의 텍스처 페치가 발생한다. 오픈월드에서 이를 해결하는 표준 구성은 세 단계다.

1. **레이어 페인팅/마스크**: Landscape Layer Blend로 바이옴 레이어(암반, 흙, 모래, 눈, 풀)를 블렌드. 가중치 합은 정규화(Weight-Blended)해서 예측 가능하게 만든다.
2. **경사·고도 기반 자동 블렌딩**: Slope(경사), Height(고도), 노이즈를 조합해 레이어 간 경계를 자동으로 만든다. 손으로 칠한 마스크와 자동 마스크를 Max/Lerp로 합성한다.
   - 급경사 → 암반, 완경사 → 흙/풀, 고도 상한 이상 → 눈, 해수면 근처 → 모래.
   - 경계 폭을 노이즈로 흔들어 직선 경계를 없앤다.
3. **원경은 RVT로**: 카메라 근처만 전체 레이어를 평가하고, 원경은 RVT에 베이크된 결과를 샘플링한다.

추가 팁:

- **Landscape Visibility Layer**로 동굴 입구·구멍을 뚫는다.
- 레이어별 텍스처는 **Virtual Texture**로 두면 원경 밉 비용이 줄어든다.
- 머티리얼 품질 스위치(`Quality`)로 원경/저사양에서 레이어 수를 줄인다.
- **Landscape Patch** 플러그인(실험)으로 특정 구역만 메시 패치로 교체할 수 있다. 절벽·아치처럼 하이트필드로 표현할 수 없는 형태에 쓴다.

### 2.4 Runtime Virtual Texture(RVT)

#### 원리

RVT는 랜드스케이프 머티리얼의 결과(베이스컬러, 노멀, 러프니스 등)를 **월드 공간 텍스처**에 한 번 렌더링하고, 지형·메시가 그 텍스처를 샘플링하게 한다.

- **Write pass**: RVT 볼륨 안의 지형을 텍스처 공간에 그린다. 화면과 무관하게, 페이징 단위로 수행된다.
- **Sample pass**: 최종 렌더링에서 복잡한 레이어 블렌딩 대신 RVT 한 번의 샘플로 대체한다.
- 효과: ① 레이어 수에 따른 픽셀 비용 제거 ② 지형과 메시(바위, 도로 데칼)의 자연스러운 블렌딩 ③ 원경 텍셀 밀도 제어.

#### 해상도와 메모리

- RVT 해상도 = **축당 타일 수 × 타일 크기**. 타일은 128 또는 256 texel이 일반적이고, 타일 수는 2의 거듭제곱, 총 타일 상한은 4,096개다.
- 타일당 페이지 테이블 엔트리(RGBA8)가 필요하고, 밉 체인 전체 타일 수는 mip0의 약 4/3이다.
- **BC 압축**을 켜면 메모리가 4~8배 줄고 샘플링도 빨라진다. 레이아웃별 텍셀당 바이트(압축):

| 레이아웃 | 포맷 | 텍셀당 |
| --- | --- | --- |
| Base Color | BC1 | 0.5 B |
| Base Color + Normal | BC1 + BC5 | 1.5 B |
| Base Color + Normal + Roughness + Specular | BC1 + BC3(패킹) | 1.5 B |
| 위 + Mask | + 8-bit | 2.5 B |

예: 8,129 m 지형을 2 m당 1텍셀(0.5 texel/m)로 덮으면 4,096×4,096, 256 타일, BC1+BC5에서 mip0 24 MB, 전체 밉 32 MB. 페이지 테이블은 1.3 KB 수준이다. **문제는 페이지 테이블이 아니라 물리 풀**이다. 런타임에는 화면이 보는 페이지만 상주하므로, cooked 빌드의 Fixed Pool 크기를 기기별로 정하고 `stat virtualtexturing` / `stat virtualtexturememory`로 eviction을 확인한다.

#### 운용 규칙

- RVT는 **한 장이 한 월드 영역**을 덮는다. 8 km를 한 장으로 덮으면 텍셀 밀도가 2 m/texel 수준으로 떨어진다. 근접 디테일이 필요하면 RVT 볼륨을 나누거나(타일별), 근접은 일반 텍스처 레이어로 보완한다.
- **Low Mips to Remove**는 원경 비용을 줄이지만 밉 shimmering을 만든다. 스트리밍 밉과 비교해 결정한다.
- **Continuous Page Updates**는 의존 텍스처 스트리밍 때문에 생기는 저해상도 페이지를 스스로 갱신한다. 비용이 들지만 초기 로딩 품질이 안정된다.
- RVT 출력 패스 안에서 일반 Virtual Texture를 샘플링하는 것은 5.6부터 완화 플래그(`bRelaxRuntimeVirtualTextureRestrictions`)가 있지만, Epic은 여전히 **비권장**이다(피드백 패스가 없어 stale 페이지가 생긴다). RVT 출력에는 전통적으로 스트리밍되는 텍스처를 쓴다.
- RVT 볼륨의 Priority로 겹치는 볼륨의 우선순위를 정한다. 지형용과 메시 블렌드용을 분리하면 디버깅이 쉽다.

### 2.5 변위와 3D 지형

UE5에서 **테셀레이션은 제거**됐다. 하이트필드 위의 미세 변위는 다음 네 가지 중 하나로 처리한다.

| 방법 | 원리 | 장점 | 한계 | 상태(5.8) |
| --- | --- | --- | --- | --- |
| **Nanite Tessellation** | 머티리얼 Displacement로 나나이트 메시를 다이싱·변위 | 지형/메시 모두, 디테일 유지, LOD 자동 | 실험. 변위 크기가 클수록 클러스터 컬링·VSM 비용 증가. UV seam 크랙 | Experimental (5.4 도입) |
| **Virtual Heightfield Mesh(VHM)** | 하이트 RVT를 버텍스 셰이더에서 샘플해 쿼드트리 메시 변위 | 대규모 지형 변위, Nanite 없이 | 콜리전 기본 없음, LOD popping, RVT 해상도에 종속, 실험 | Experimental |
| **Mesh Terrain** | 3D 메시 기반 지형(섹션 + 비파괴 모디파이어) | 오버행·동굴·부유섬. Nanite 런타임 데이터. WP/OFPA/PCG 통합 | 5.8 첫 실험 릴리스. 프로덕션 사용 비권장 | Experimental |
| **Landscape Patch / 메시 대체** | 특정 구역만 스태틱 메시로 교체 | 국소 절벽·아치에 즉시 적용 | 경계 블렌딩 수작업, 콜리전 별도 | 플러그인 |

#### Nanite Tessellation 실무 주의점

- 변위 **Fade(Start/End)** 는 선택이 아니라 필수다. 원경에서 변위를 꺼야 다이싱 비용이 사라진다.
- `r.Nanite.DicingRate`로 화면 공간 다이싱 크기를 조절한다. 3~4에서 성능이 오르는 경우가 많지만 콘텐츠별로 `stat GPU`로 확인한다.
- **Landscape의 기본 Z scale 100**에서는 변위 Magnitude 4가 400 uu(4 m)다. 지형에 쓸 때는 스케일을 반드시 확인한다.
- 변위가 크면 클러스터 바운드가 부풀어 컬링 효율이 떨어지고 오버드로가 늘어난다. 캐릭터 발 IK·충돌에 영향을 주는 크기라면 변위가 아니라 지형 자체를 고친다.

#### Virtual Heightfield Mesh 주의점

- 하이트 RVT가 없으면 동작하지 않는다. RVT 해상도가 곧 지형 실루엣 해상도다.
- 기본적으로 **콜리전이 없다**. 플레이어가 지형을 뚫는 문제는 별도 콜리전 메시나 Landscape 콜리전과의 정합으로 해결해야 한다.
- LOD 전환에서 지형이 물결처럼 흔들리는 popping이 보고된다. 5.8에서는 버텍스 셰이더의 VT 피드백 레벨 인코딩이 엔진과 어긋나 생기는 popping이 커뮤니티에서 보고됐다(2026-07, 엔진 수정 전). 채택 전에 5.8.x 핫픽스에서 재현 테스트를 한다.

#### Mesh Terrain(5.8 실험)의 구조

- **Base Section**: 임의로 분할된 삼각형 메시 조각. 모양 제약이 없다(POI 단위로 잘라도 된다).
- **Modifier**: 베이스 섹션에 비파괴로 적용되는 변형(텍스처 변위, 불리언, 스컬프트). 우선순위·그룹으로 적용 순서를 정하고, 의존 그래프로 캐시·병렬 처리한다.
- **Intermediate / Runtime Data**: 편집 중에는 프리뷰 메시, 빌드 시에는 플랫폼별 런타임 데이터(하이엔드 Nanite, 모바일 스태틱 메시 LOD)로 변환한다.
- World Partition·OFPA와 통합되어 섹션 단위로 부분 로드·부분 편집이 가능하다.

즉 Mesh Terrain은 "Landscape의 3D 버전"이라기보다 **대형 메시를 스트리밍 단위로 쪼개 편집·렌더링하는 시스템**이다. 5.8은 첫 실험이고 Epic도 "6개월 뒤 5.9에서 바뀔 수 있다"고 명시하므로, 학습·프로토타입에는 쓰되 양산 파이프라인의 단일 경로로 삼지 않는다.

---

## 3. 월드 스트리밍과 공간 분할

### 3.1 서브레벨 패러다임의 한계

UE4식 월드 컴포지션/서브레벨은 다음 문제를 만든다.

- 레벨 파일 하나를 여러 사람이 동시에 편집할 수 없다(체크아웃 잠금).
- 서브레벨 경계를 넘는 액터 참조가 로드 순서·누락 문제를 만든다.
- 전체 월드를 한눈에 보기 어렵고, 원경 표현(HLOD)을 수동으로 맞춰야 한다.
- 스트리밍 단위(서브레벨)와 제작 단위(구역)가 어긋난다.

World Partition은 **하나의 Persistent Level + 자동 그리드 + OFPA**로 이 문제를 구조적으로 없앤다.

### 3.2 World Partition 구성 요소

| 요소 | 설정 위치 | 역할 |
| --- | --- | --- |
| Runtime Grid | World Settings > World Partition Setup | Cell Size, Loading Range, Block on Slow Streaming, Priority. 기본 2D 해시 그리드 1개. **그리드를 여러 개 쓰면 성능이 나빠진다** |
| Streaming Source | PlayerController(기본), `UWorldPartitionStreamingSourceComponent` | 반경 내 셀을 로드. Shape/Priority/Target State(Loaded/Activated) 지정 가능 |
| Is Spatially Loaded | 액터 Details > World Partition | 끄면 거리와 무관하게 항상 로드(매니저, 백드롭) |
| Data Layer | Data Layer Asset + 액터 할당 | 게임 상태에 따른 조건부 로드 |
| HLOD Layer | HLOD Layer Asset | 언로드 셀의 원경 대체물 |
| Runtime Hash | World Partition 설정 | 셀 배치 규칙(기본 LH Grid: 경계에서 약간 넘치면 셀을 늘림) |

에디터에서는 월드가 기본적으로 **언로드 상태**로 열리고, `Is Spatially Loaded = false`인 액터만 로드된다. 그래서 "에디터에서 안 보인다"는 대부분 버그가 아니라 설정이다. Preview Grids를 켜서 셀 경계를 확인한다.

디버깅 콘솔:

```
wp.Runtime.OverrideRuntimeSpatialHashLoadingRange -grid=0 -range=200000
wp.Runtime.MaxLoadingLevelStreamingCells 32
stat levels
stat streaming
```

5.8부터 Unreal Insights에 **Spatial Profiler** 탭이 생겼다. 월드 스트리밍 트레이스(`WorldStreaming` 채널)를 시간축으로 재생하고, 셀 단위 로드/언로드·메모리를 2D 월드 뷰로 본다. `wp.Editor.ExportMinimapForInsights`로 미니맵 PNG와 월드 경계 JSON을 뽑아 배경으로 쓸 수 있다. 오픈월드 프로젝트라면 이 도구를 첫 주에 세팅한다.

### 3.3 Data Layer: 상태를 공간에서 분리하기

Data Layer는 "지금 이 액터가 월드에 있어야 하는가"를 **거리와 별개로** 결정한다.

- **Editor vs Runtime**: 에디터 전용(작업 편의)과 런타임 전환용을 구분한다.
- **초기 상태**: Loaded / Unloaded / Activated.
- **전환**: 블루프린트 `Set Data Layer State`(또는 C++ `UDataLayerManager::SetDataLayerRuntimeState`). 전환 시 해당 액터들이 로드/언로드되므로 **프레임 히치**가 발생할 수 있다. 큰 레이어는 전환 전에 스트리밍 소스로 미리 로드하거나, 전환을 컷신/로딩 화면 뒤에 둔다.

전형적인 분리:

| 레이어 | 내용 | 전환 시점 |
| --- | --- | --- |
| DL_Day | 낮 소품, 시장, NPC | 시간대 |
| DL_Night | 밤 조명, 야시장, 몬스터 스폰 | 시간대 |
| DL_Quest_03 | 퀘스트 3 전용 구조물/폐허 | 퀘스트 진행 |
| DL_Destruction_A | 파괴 전/후 상태 | 이벤트 |
| DL_Season_Winter | 눈 더미, 얼음 | 계절/챕터 |

주의: Data Layer와 HLOD는 함께 동작해야 한다. 액터가 꺼진 레이어에 있는데 HLOD 프록시가 남으면 유령 건물이 보인다. HLOD 빌드 시 데이터 레이어 조합별 프록시가 생성되는지 확인한다.

### 3.4 OFPA(One File Per Actor)와 협업

- 모든 액터는 `__ExternalActors__` 아래 개별 파일로 저장된다. 레벨 파일을 잠그지 않고 동시 편집이 가능하다.
- 액터 간 **하드 참조는 함께 번들**되어 로드된다. 셀 경계를 넘는 참조는 스트리밍 단위를 오염시키므로, 참조 대신 인터페이스/이벤트/소프트 참조를 쓴다.
- Git에서 `.uasset`은 바이너리다. 같은 파일을 두 사람이 건드리면 병합이 불가능하다. OFPA는 그 충돌 단위를 액터 1개로 줄여줄 뿐, 같은 액터 동시 편집은 여전히 충돌한다.
  - 대규모 팀: Perforce/Plastic + 파일 잠금.
  - Git: Git LFS, `git config merge.ours.driver` 같은 우회는 위험. **액터 소유 구역을 나누고, 서브레벨 대신 Data Layer/Level Instance로 작업 경계를 만든다.**
- 텍스트 기반 자산(Data Layer Asset, HLOD Layer Asset, PCG 그래프의 일부)은 리뷰가 가능하지만, 그래프 노드 그래프 자체는 바이너리인 경우가 많다.

### 3.5 스트리밍 성능 관리

1. **셀당 데이터량을 측정**한다. `stat levels`로 셀별 로드 시간, `stat memory`/Insights로 셀별 메모리를 본다. 한 셀이 다른 셀의 3배면 콘텐츠를 분할한다.
2. **Block on Slow Streaming**은 안전장치지만, 켜면 플레이어가 멈춘다. 켠 상태로 최악 동선을 테스트해 "멈추지 않는" 것을 확인한 뒤 끈다.
3. **동시 로드 셀 상한**을 둔다(`wp.Runtime.MaxLoadingLevelStreamingCells`). 상한에 걸리면 로딩이 순차화되어 히치가 줄지만 빈 셀이 보일 수 있다.
4. **GC 압박**을 관리한다. 언로드 대기 액터가 쌓이면 GC가 몰린다. 5.8의 pending-actor 기반 GC 옵션을 검토한다.
5. **텔레포트/패스트 트래블**: 목적지에 `Streaming Source Component`를 미리 활성화하고 `Is Streaming Completed`를 기다린 뒤 플레이어를 옮긴다. 컷신도 같은 방식.
6. **Fast Geometry Streaming**: 비게임플레이 정적 지오메트리를 분리해 스트리밍 히치를 줄인다(실험).

### 3.6 Level Instance와 재사용

- 반복되는 건물군·폐허·마을 블록은 Level Instance(또는 Packed Level Actor)로 묶는다. 메모리·드로우콜·빌드 시간이 줄고, 한 곳을 고치면 모든 인스턴스가 갱신된다.
- 단, Level Instance 내부는 하나의 스트리밍 단위로 취급된다. 거대한 인스턴스는 셀 하나에 다 들어가므로, 인스턴스 크기를 셀 이하로 유지한다.
- 인스턴스 안의 액터는 별도 Data Layer 전환이 어렵다. 상태가 바뀌는 콘텐츠는 인스턴스 밖에 둔다.

---

## 4. PCG와 식생

### 4.1 바이옴 설계

바이옴은 "어디에 무엇이 자라는가"의 규칙이다. 가장 널리 쓰이는 기준은 **Whittaker 다이어그램**(연평균 기온 × 연강수량)으로, 툰드라·침엽수림·온대활엽수림·초원·사막·열대우림을 나눈다. 게임에서는 실제 기후 모델을 돌리기보다, 지형에서 유도한 값으로 같은 분포를 만든다.

| 바이옴 입력 | 유도 방법 | 용도 |
| --- | --- | --- |
| 기온 | 위도 + 고도(기온 감률) + 노이즈 | 수종, 눈선 |
| 습도/강수 | 유역 면적(flow accumulation), 호수 거리, 안개 | 초원/습지/사막 |
| 경사 | 지형 노멀 | 암반 노출, 식생 밀도 |
| 고도 | 하이트맵 | 수목 한계선, 설선 |
| 토양/지질 | 마스크 텍스처(외부 DCC) | 바위/모래/점토 |
| 교란 | 화산/화재/폐허 마스크 | 천이 초기 식생 |

실무 순서:

1. 외부 DCC에서 **바이옴 ID 맵**(0~N)과 바이옴별 마스크를 만든다. 경계는 노이즈로 흔들어 자연스럽게.
2. 경계 폭(블렌드 구간)을 정한다. 하드 경계는 게임적으로 읽기 쉽지만 자연스럽지 않다. 보통 50~200 m.
3. 바이옴마다 PCG 그래프를 하나씩 두고, 공통 그래프 + 파라미터(종 목록, 밀도, 크기 분포)로 변형한다.
4. 물/습지/절벽 같은 **예외 마스크**를 최우선 필터로 둔다(나무가 물 위에 서지 않게).

### 4.2 PCG 프레임워크 구조

PCG는 "포인트 집합 + 속성"을 노드 그래프로 변환해 액터/인스턴스를 생성한다.

- **입력**: PCG Volume, Landscape, Spline, Static Mesh, Data Asset, 액터 태그.
- **포인트 데이터**: 위치 + 회전 + 스케일 + 임의 속성(float, vector, string, tag). 5.8에서 배열·구조체·집합·맵 같은 복합 속성을 지원해 건물·거리 생성이 가능해졌다.
- **노드 계열**: Sampler(Landscape Surface, Spline, Mesh, Volume), Filter(Density, Slope, Height, Attribute, Self Pruning, Difference), Transform, Copy Points, Spawn(Static Mesh, Actor, Spline), Partition, Subgraph.
- **실행**: 에디터에서 베이크(생성 결과를 액터로 저장)하거나, 런타임 생성(PCG Component의 Generate on Load/Runtime). 런타임 생성은 메모리·CPU를 쓰지만 월드 상태 변화에 반응할 수 있다.
- **파티션**: 큰 월드를 셀 단위로 나눠 생성·스트리밍한다. World Partition의 Data Layer/HLOD Layer와 자동으로 연동된다.

5.7에서 PCG가 프로덕션 레디가 됐고, 5.8에서 **생성 결과 위에 수동 편집을 얹어도 절차성이 깨지지 않는** 워크플로가 들어왔다. 이게 중요한 이유는 실무에서 100% 절차 생성으로 끝나는 오픈월드가 없기 때문이다. "PCG로 90% 깔고, 랜드마크만 손으로"가 가능해졌다.

성능 관련 5.8 개선: 포인트 데이터 옥트리를 지연 할당해 10만 포인트당 약 400 MB를 절약, 런타임 생성 스케줄러 게임 스레드 비용 최대 30% 감소, `pcg.RuntimeGeneration.TimeBetweenRuntimeGenSchedulerTicks`로 스케줄링 간격 조절.

### 4.3 예제 그래프: 바이옴 → 밀도 → 스폰

| 단계 | 노드 | 설정 | 이유 |
| --- | --- | --- | --- |
| 1 | Landscape Surface Sampler | 바이옴 영역, 포인트 간격 4 m | 균일 샘플 |
| 2 | Attribute Filter | Biome == TemperateForest | 바이옴 분리 |
| 3 | Density Filter (Noise) | 0.6~1.0, 스케일 200 m | 군락/공터 |
| 4 | Slope Filter | 0~35° | 절벽 회피 |
| 5 | Difference (Water Mask) | 호수/강 마스크 제외 | 물 위 나무 방지 |
| 6 | Self Pruning | 반경 3 m | 최소 간격 |
| 7 | Transform Points | 랜덤 회전 Y, 스케일 0.8~1.3 | 자연스러운 변이 |
| 8 | Weighted Mesh Selector | 참나무 60 / 소나무 30 / 관목 10 | 종 구성 |
| 9 | Static Mesh Spawner | HISM, 그림자 on(대형만) | 드로우콜 절감 |
| 10 | Partition | 256 m 그리드 | 셀 스트리밍 연동 |

도로/강을 따라 배치할 때는 Spline Sampler + Spline Offset(거리별 밀도 감소)를 쓴다. 마을/폐허는 Volume Sampler + Difference로 건물 footprint를 비운다.

**계층적 스폰**은 대규모 월드에서 필수다. 한 그래프에서 수백만 포인트를 직접 스폰하면 메모리와 생성 시간이 폭발한다. 보통 ① 바이옴/구역 단위의 거친 포인트(수십 m 간격) → ② 군락/클러스터 포인트(수 m 간격) → ③ 개별 인스턴스(1 m 이하)로 단계를 나누고, 각 단계의 결과를 다음 그래프의 입력으로 넘긴다. 중간 단계에서 Self Pruning/Density Filter로 수를 줄이면 최종 인스턴스 수를 예측할 수 있다. PCG Partition은 이 계층을 셀 단위로 잘라 스트리밍한다. 절차 생성 결과 위에 손으로 랜드마크를 얹는 경우, 5.8의 수동 편집 레이어를 쓰면 상위 파라미터를 바꿔도 손편집이 유지된다.

### 4.4 대규모 식생 렌더링

| 방식 | 드로우콜 | 장점 | 단점 |
| --- | --- | --- | --- |
| 개별 Static Mesh | 인스턴스당 1+ | 단순 | 수천 개에서 즉사 |
| ISM | 메시당 1 | 배칭 | 컬링 단위 큼, 개별 LOD 없음 |
| **HISM** | 메시당 1 + 클러스터 | 계층 컬링, LOD, 대규모 | WPO 비용, 클러스터 경계 |
| **Nanite Foliage**(5.7 실험) | 클러스터 GPU 컬링 | 수백만 인스턴스, LOD 없음, voxel 원경 | 빌드 시간·메모리, 실험 단계, USD/에셋 파이프라인 제약 |

#### HISM 운용

- 나무·바위는 HISM, 작은 풀은 별도 HISM(그림자 off, cull distance 짧게).
- 인스턴스 추가/제거는 런타임에 가능하지만, 대량 변경은 클러스터 재구성 비용이 든다. 파괴 가능한 오브젝트는 ISM/HISM에서 빼고 개별 액터로.
- WPO(바람)를 쓰면 바운드가 커져 컬링이 무뎌진다. `World Position Offset Disable Distance`로 원경 WPO를 끈다.
- **Pivot Painter 2**: 나무·풀의 줄기/잎 피벗을 텍스처에 구워 WPO로 계층적 바람을 주는 전통 기법. Nanite Foliage의 스키닝 바람이 없는 프로젝트(모바일, 비-Nanite)에서 여전히 표준이다. 정점 수 × 인스턴스 수에 비례하므로 원경에서는 꺼야 한다.

#### Nanite Foliage(5.7/5.8)

- **Nanite Assemblies**: 나무를 가지/잎 조각의 인스턴스 조합으로 표현. 에셋 크기·메모리가 줄고 변형을 재사용할 수 있다. USD 임포트 시 `NaniteAssemblyRootAPI` 메타데이터가 필요하다.
- **Nanite Voxels**: 원경에서 삼각형 대신 voxel로 전환. 임포스터와 달리 어느 각도에서나 부피가 유지되고, 전환이 눈에 덜 띈다. 빌드 시간이 늘어난다(ray 수 조절 가능).
- **Nanite Skinning + Dynamic Wind**: WPO 대신 본으로 바람을 준다. 수백~1,000 본 수준이 실용적이며, 바운드 제어가 쉬워 컬링 효율이 좋다.
- **PVE(Procedural Vegetation Editor, 5.8 실험)**: 나무를 키우고(광량 경쟁, 군락 형성) Nanite-ready 스켈레탈 메시로 내보낸다. 외부 DCC 메시를 PVE 호환으로 변환하는 것도 가능.
- 주의: Nanite Foliage는 5.8에서도 Experimental이다. 마스크드 머티리얼 기반의 기존 폴리지는 여전히 유효하며, Nanite는 **불투명 지오메트리**에 강하다. 잎을 알파 마스크로 만들면 Nanite 이점이 줄어든다. Voxel/Assembly 빌드 시간과 메모리를 양산 전에 측정한다.
- `Nanite Pixel Programmable Distance`(5.8 폴리지 타입 속성)로 원경 픽셀 셰이더 비용을 줄인다.

### 4.5 식생 비용 예산

- **인스턴스 예산**: 화면 내 100만 인스턴스가 아니라, **화면 내 픽셀 커버리지와 오버드로**로 예산을 잡는다.
- **그림자**: 작은 풀·관목은 그림자 캐스터를 끈다. 나무 그림자는 VSM 페이지를 많이 먹는다.
- **오버드로**: 풀 카드는 겹침이 심하다. 카메라 근접에서 레이어 수를 줄이고, Far Distance에서 카드 크기를 키운다.
- **컬링**: HISM 클러스터 크기(보통 256~1024 m)를 셀 크기와 맞춘다. 너무 작으면 CPU, 너무 크면 GPU.
- **바람**: WPO는 정점 수 × 인스턴스 수에 비례. 원경은 WPO off, 근경만 on.

---

## 5. 인프라: 도로와 수계

### 5.1 스플라인 기반 도로

도로는 지형 위에 "그려지는" 것이 아니라 지형을 **변형**한다. 두 가지 경로가 있다.

**A. 엔진 내 Landscape Spline**

1. Landscape Spline으로 중심선을 깐다. Control Point에서 폭, 단면(평평/둑), 좌우 Falloff를 지정한다.
2. `Apply Spline Deform`으로 지형을 깎고 다진다. 세그먼트가 많을수록 정밀하지만 비용이 든다.
3. 도로 표면은 데칼(Asphalt) 또는 별도 메시(도로 키트)로 덮는다. 데칼은 경사면에서 늘어나므로, 급경사 구간은 메시를 쓴다.
4. 도로변 소품(가로등, 표지판, 가드레일)은 PCG Spline Sampler로 10~30 m 간격 배치.
5. 교차로는 스플라인을 합치지 말고 **평면 패치**(Intersection 메시)로 처리한다. 스플라인끼리 교차하면 지형이 꼬인다.

**B. 외부 DCC에서 도로 네트워크를 지형에 굽기**

Houdini에서 도로 네트워크를 생성하고, 도로 마스크로 높이를 평탄화한 뒤 하이트맵과 함께 익스포트한다. 대규모 도시·왕복 도로망은 이쪽이 안정적이다. 엔진에서는 도로 마스크 레이어로 재질만 입힌다.

공통 주의점:

- **경사 한계**: 도로 종경사 8~12%를 넘으면 차량/도보 이동이 어색해진다. 스플라인을 지형에 맞추기 전에 경사 검사를 한다.
- **배수**: 도로는 유역을 가로지른다. 강과 만나는 지점은 교량/암거를 계획한다.
- **내비게이션**: 도로는 NavMesh에 반영되어야 한다. 폭이 좁으면 내비 타일이 끊긴다.
- **LOD/스트리밍**: 긴 스플라인은 셀 경계를 넘는다. 스플라인 액터를 셀에 맞춰 자르거나, 도로 메시를 셀 단위로 베이크한다.

### 5.2 수계 시스템

UE5의 Water 플러그인은 Water Body 액터로 강·호수·바다를 만들고, Water Zone이 그 위에 연속 메시를 생성한다.

| 요소 | 역할 |
| --- | --- |
| Water Body River | 중심 스플라인을 따라 흐르는 강. 폭·깊이·유속 프로필 |
| Water Body Lake | 닫힌 해안 스플라인 안쪽의 정수면 |
| Water Body Ocean | 해안 스플라인에서 원경까지 바다 |
| Water Body Custom/Transition | 게임플레이용 커스텀 수역(메시 필요) |
| Water Zone | 수역 전체를 덮는 쿼드트리 메시 + 원경 메시 |
| Water Waves Asset | 파도 시뮬레이션 모델. 기본 Gerstner |
| Water Material | 표면 셰이딩(반사, 굴절, 거품, 깊이 기반 색) |

**Gerstner 파도**: 여러 사인파를 합성해 파고·파장·방향·급경사를 만든다. 기본 16개 파도. 파도 수를 줄이면 성능이 오르지만 반복 패턴이 보인다. Seed/Randomness로 변이를 준다. 미세 디테일은 노멀맵으로, 거시 운동은 파도 모델로 나누는 것이 표준이다.

**렌더링**: 단일 레이어 워터(Single Layer Water) 머티리얼, 깊이 기반 흡수, 수면 반사(Lumen/SSR), 수중 포스트 프로세스(안개, 색수차, 굴절). 5.8에서 모바일 수중/수면 렌더링 품질이 개선됐다.

**게임플레이 연계**:

- `UBuoyancyComponent` + Pontoons(구형 샘플점)로 부력. Pontoon 반경/위치, `BuoyancyCoefficient`, `MaxBuoyantForce`, damping을 튜닝한다.
- 강에서는 `bApplyRiverForces`, `WaterVelocityStrength`, `WaterShorePushFactor`로 하류로 밀어낸다.
- 수면 높이 질의: `GetWaterSurfaceInfoAtLocation`(파도 포함), `UWaterSubsystem::GetOceanTotalHeight`.
- 수영/잠수: 수면 아래 진입 시 수중 볼륨/포스트 프로세스 전환, 산소/수영 상태 머신.
- 보트: 부력 + 추진 + 조향. 파도 응답이 너무 크면 Pontoon damping을 올린다.

주의: Water 플러그인은 5.8에서도 **v0.1 Experimental**이다. API가 바뀔 수 있고, 대규모 바다의 원경 메시·LOD·모바일 경로는 프로젝트별 검증이 필요하다. 자체 수면 셰이더로 대체하는 선택도 흔하다.

### 5.3 수계와 지형의 정합

- 강은 지형보다 먼저 계획한다(2.1). 강 마스크로 지형을 깎고, Water Body River의 스플라인을 같은 경로에 맞춘다.
- 호수는 수면 높이가 일정해야 한다. 지형의 유역 최저점과 Water Body의 높이를 일치시키고, 범람 지점을 마스크로 평탄화한다.
- 해안선은 파도 침식 마스크와 일치시킨다. 모래/자갈 레이어 경계가 해수면과 어긋나면 즉시 티가 난다.
- 수중 지형(호수 바닥)은 별도 해상도로 관리한다. 수면 아래는 원경 LOD가 빨리 떨어져도 된다.

---

## 6. 대기·하늘·라이팅

### 6.1 Sky Atmosphere

물리 기반 대기 산란(레일리/미 산란)으로 하늘 색, 태양 주변 광휘, 지평선 안개를 만든다.

- Directional Light(태양)와 함께 두면 대기 산란이 자동으로 계산된다.
- **Aerial Perspective**: 원경이 거리에 따라 하늘색으로 바래는 효과. 오픈월드 원경의 깊이감을 만든다. `Aerial Perspective View Distance`를 시야 거리에 맞춘다.
- 태양 각도가 낮을수록 산란이 길어져 붉어진다. 시간대 순환의 핵심 파라미터는 **태양 고도**와 **방위각**이다.
- Sky Light: 대기에서 간접광을 캡처. 실시간 캡처는 비싸므로, 시간대 변화가 느리면 주기적 캡처(예: 30초)로 충분하다.

### 6.2 Volumetric Cloud

- 볼류메트릭 클라우드는 카메라 주변의 구름 볼륨을 레이마칭한다. **로컬 볼륨**이므로 원경 하늘 전체를 덮지 않는다. 원경 구름은 Sky Atmosphere/스카이박스나 원경 클라우드 레이어로 보완한다.
- Coverage(운량), Altitude(고도), Extinction/Scattering, Wind로 형태를 만든다. Material로 커스텀 노이즈를 넣을 수 있다.
- 비용: 해상도·스텝 수·그림자(구름이 지표에 드리우는 그림자)가 주요 변수. `r.VolumetricCloud.*`로 품질을 조절한다.
- 구름 그림자는 Lumen/VSM과 상호작용한다. 구름이 태양을 가리면 간접광이 급변해 깜빡임이 생길 수 있다.

### 6.3 Exponential Height Fog

- 고도에 따라 지수적으로 감소하는 안개. 지표 근처 안개, 계곡 안개, 원경 안개를 만든다.
- **Volumetric Fog**를 켜면 빛줄기(라이트 샤프트)와 국소 안개가 가능하지만 비용이 든다. 오픈월드에서는 원경은 Height Fog, 근경은 Volumetric Fog로 역할을 나눈다.
- Fog Inscattering Color와 Directional Inscattering으로 일출/일몰의 색을 강조한다.

### 6.4 Lumen

Lumen은 오픈월드 GI의 기본 경로다. 두 가지 레이트레이싱 모드를 지원한다(5.8 기준 HW RT가 기본, 지원 기기에서).

| | Software RT | Hardware RT |
| --- | --- | --- |
| 대상 | Mesh Distance Field(SDF) | 실제 삼각형 |
| 장점 | 모든 SM6 기기, 겹친 인스턴스에 강함 | 정확한 반사, 디테일 |
| 한계 | 얇은 지오메트리 누광, SDF 해상도 | 비용, 지원 기기, BVH 메모리 |
| 거리 | Lumen Scene 기본 200 m(최대 800 m) | Far Field 최대 1 km(기본) |

핵심 개념:

- **Surface Cache**: 메시를 카드(기본 12장)로 캡처해 간접광을 계산. Nanite가 캡처를 가속한다. 카드가 없는 영역은 분홍색으로 표시되고 빛을 반사하지 않는다.
- **Lumen Scene**: 카메라 주변의 GI 표현. SW RT에서는 200 m(최대 800 m)까지만 덮고, 그 밖은 스크린 트레이스만 남는다.
- **Far Field**: HW RT에서 1 km까지 GI/반사를 확장. **HLOD1 프록시가 필수**이고 `r.LumenScene.FarField=1`로 켠다. 레이 트레이싱 컬링 반경(`r.RayTracing.Culling.Radius`)과 Far Field 최대 거리를 맞추지 않으면 근경/원경 사이에 커버리지 구멍이 생긴다.
- **Lumen Lite(5.8)**: Medium 스케일러빌리티의 새 경로. Irradiance Field + Probe Occlusion 기반으로 High 대비 약 2배 빠르며, 핸드헬드/저사양 PC에서 60 fps를 노린다. 여전히 Beta 표기.
- **MegaLights(5.8 프로덕션)**: 다수의 그림자 광원을 GPU에서 처리. 밤 마을/실내 조명 밀도를 크게 올릴 수 있다. 기본 경로는 아니므로 프로젝트에서 명시적으로 켠다.

오픈월드 운용:

- 빠른 이동/카메라 컷에서 Lumen Scene 갱신이 뒤처져 간접광이 늦게 뜬다. 텔레포트·컷신에서는 한두 프레임 프리웜(prewarm)하거나 컷 전에 카메라를 미리 이동시킨다.
- 원경 건물이 Lumen Scene에서 빠지면 반사에서 사라진다. Far Field/HLOD로 보완한다.
- 식생은 Nanite + Surface Cache가 아니면 캡처가 느리다. Nanite foliage를 쓰면 GI 반응이 좋아진다.
- 실내(동굴)에서는 Lumen만으로 부족할 수 있다. 포인트/스포트 라이트 + Distance Field AO를 함께 쓴다.

### 6.5 Virtual Shadow Map(VSM)

VSM은 그림자를 페이지 단위로 캐시하는 가상화 기법이다.

- 방향광은 클립맵, 로컬 라이트는 큐브맵/2D 페이지로 관리한다.
- 한 번 그린 페이지는 재사용하고, 물체/광원/카메라가 바뀔 때만 무효화한다.
- **비용**: 페이지 풀 크기, 무효화 빈도(움직이는 물체, WPO, Nanite LOD 변화), 그림자 캐스터 수.
- 5.8: `r.Shadow.Virtual.DeferredInvalidationBudget`로 Nanite LOD 변화에 의한 무효화를 예산 내로 제한. Prefiltered Distant(실험)로 원경 캐스터를 낮은 해상도로 그려 부드럽게 합성.
- 오픈월드 팁:
  - 작은 폴리지/소품은 그림자 캐스터를 끈다.
  - HLOD 프록시는 그림자를 끈다(`wp.Runtime.HLOD.ForceDisableShadows`).
  - 태양이 움직이는 시간대 순환에서는 캐시가 매 프레임 무효화된다. 태양 각도를 일정 시간(예: 1분)에 1도씩만 움직이거나, 캐시 갱신을 프레임 분산한다.
  - Nanite Tessellation 변위는 VSM 비용을 크게 올린다. 변위 Fade를 적극적으로.

### 6.6 시간대 순환(Time of Day)

구성 요소:

1. **태양/달 궤도**: 위도·경도·날짜로 방위각/고도를 계산(또는 Sun Position 플러그인). 하루 길이를 게임 시간에 매핑.
2. **Sky Atmosphere**: 태양 고도에 따른 산란. 일출/일몰 색.
3. **Sky Light**: 주기적 캡처 또는 실시간. 캡처 주기와 노출을 고정.
4. **안개/구름**: 시간대별 색·밀도 커브.
5. **인공 조명**: 해 진 후 켜지는 조명. MegaLights로 밀도 확보.
6. **노출**: Auto Exposure는 밤/낮 전환에서 화면이 멍해진다. **고정 노출 + 수동 EV 보정**이 오픈월드에서 예측 가능하다. 필요하면 시간대별 EV 커브.
7. **그림자**: 태양이 낮게 있으면 그림자가 길어져 VSM 페이지 수요가 급증한다. 일출/일몰 구간을 별도 프로파일링한다.

밤 조명은 "빛이 적어서 싸다"가 아니다. 그림자 광원이 많아지고, Lumen이 어두운 장면에서 노이즈를 내며, MegaLights/VSM 비용이 오른다. 밤 마을 하나를 vertical slice로 잡아 비용을 측정한다.

---

## 7. 렌더링 최적화와 프로파일링

### 7.1 최적화 순서

1. **예산 확정**: 프레임/메모리/스트리밍/빌드 시간.
2. **측정**: 같은 동선, 같은 시간대, 같은 카메라로 반복 측정. Insights 트레이스와 스크린샷을 남긴다.
3. **큰 것부터**: 드로우콜 → 그림자 → 오버드로 → 텍스처 → 스트리밍 → GC 순으로 줄인다.
4. **회귀 방지**: 야간 빌드에서 자동 측정, 임계값 초과 시 알림.

### 7.2 HLOD

HLOD는 언로드된 셀의 콘텐츠를 원경용 프록시로 대체한다.

| 레이어 타입 | 동작 | 적합한 콘텐츠 |
| --- | --- | --- |
| Instancing | 원본 메시를 최저 LOD ISM으로 대체 | 나무, 폴리지, 반복 프랍 |
| Merged Mesh | 여러 메시를 하나의 프록시로 병합 | 건축 클러스터, 모듈 키트 |
| Simplified Mesh | 병합 + 메시 단순화 | 비반복 암석, 지형 인접 구조물 |
| (Approximated) | 복셀화 근사 | 도시 스카이라인(CitySample 사례) |

- **HLOD Layer**마다 Cell Size와 Loading Range를 가진다. 월드 셀의 배수로 잡아야 프록시가 셀 경계에 걸치지 않는다(예: 월드 256 m, HLOD0 512 m, HLOD1 2,048 m).
- Merged/Simplified 레이어는 소스 머티리얼을 **HLODMaterial로 베이크**한다. 텍스처 아틀라스 해상도가 프록시 품질과 메모리를 좌우하므로, 원경에서 읽히는 실루엣·색만 남기고 해상도를 낮춘다. 라이트맵 UV 생성·콜리전 병합 옵션은 프록시 용도에 맞게 끈다.
- **Lumen Far Field는 HLOD1을 요구**한다. 원경 GI를 원하면 HLOD 계층을 최소 2단 구성한다.
- 빌드는 `Build > Build HLODs` 또는 `WorldPartitionHLODsBuilder` 커맨드렛. 대규모 월드는 몇 시간이 걸리므로 CI에 넣는다.
- 5.8: **HLOD Rebuild Policy**에 이미지 비교(SSIM)가 추가되어, 시각적으로 의미 없는 변경에는 재빌드를 건너뛴다. 편집기 HLOD 가시성 갱신 비용도 대폭 개선됐다(6,061개 HLOD 액터 기준 25.1 ms → 0.18 ms).
- 프록시는 그림자를 끄고, 머티리얼은 베이크된 단순 머티리얼을 쓴다.

### 7.3 컬링

- **HZB 오클루전**: 깊이 버퍼 기반 계층적 컬링. Nanite와 일반 메시 모두. 큰 건물/지형 뒤의 콘텐츠를 제거한다. 오픈월드에서 1차 방어선.
- **거리 컬링**: `Cull Distance Volume`, 액터별 Max Draw Distance. 소품/폴리지에 필수.
- **Precomputed Visibility**: 정적 실내/도시 블록에는 유효하지만, 스트리밍되는 오픈월드 전체에는 부적합.
- **컬링 단위**: HISM 클러스터, HLOD 셀, Nanite 클러스터. 단위가 너무 작으면 CPU, 너무 크면 GPU.
- **그림자 컬링**: `r.Shadow.*` 거리/캐스터 필터. 원경 소품의 그림자 캐스터를 끈다.

### 7.4 텍스처 스트리밍과 비디오 메모리

- **텍스처 풀**: `r.Streaming.PoolSize`(기기별). 너무 작으면 밉이 계속 evict되어 흐려지고, 너무 크면 다른 시스템을 압박한다.
- **Virtual Texture 풀**: RVT/스트리밍 VT는 별도 물리 풀. `stat virtualtexturing`, `stat virtualtexturememory`로 확인. cooked 빌드에서는 Fixed Pool로 고정한다.
- **텍스처 그룹/Device Profile**: 플랫폼별 LOD Bias, 최대 해상도, 밉 제한.
- **메모리 캡**: 콘솔은 하드 캡이 있다. PC는 VRAM 예산을 정하고 `stat unit`의 VRAM Used/Budget으로 확인.
- **RVT 저밉**: 원경 밉을 스트리밍하면 메모리는 줄지만 shimmering이 생긴다. `Low Mips to Remove`와 비교.

### 7.5 GPU 비용 항목

| 항목 | 주요 변수 | 줄이는 법 |
| --- | --- | --- |
| Nanite | 클러스터 수, 머티리얼 복잡도, 오버드로 | 머티리얼 단순화, 변위 Fade, `r.Nanite.DicingRate` |
| Lumen | Lumen Scene 범위, 카드 수, 트레이스 거리 | Lumen Lite, Max Trace Distance, Far Field 조정 |
| VSM | 캐스터 수, 해상도, 무효화 | 소품 그림자 off, 태양 이동 완만, Deferred Invalidation Budget |
| 베이스 패스 | 오버드로, 복잡한 머티리얼 | 폴리지 카드, 마스크드 머티리얼 최소화 |
| 대기/구름 | 해상도, 스텝, 그림자 | 품질 스케일, 원경 클라우드 단순화 |
| 물 | 파도 수, 테셀레이션, 반사 | 파도 수 감소, 원경 메시 LOD |
| 포스트 | TSR, DOF, 블룸 | 해상도 스케일, 품질 프리셋 |

### 7.6 CPU 비용 항목

- **액터 Tick**: 원경/비활성 액터는 Tick을 끈다. `Tick Interval`, `bCanEverTick`.
- **GC**: 액터 수가 많을수록 GC 시간이 길다. UObject 수 카운터(5.8 Insights)로 추적.
- **스트리밍**: 셀 로드/언로드, 텍스처 요청, 내비 타일.
- **PCG 런타임 생성**: 파티션 단위로 분산, 스케줄러 간격 조절.
- **물리/내비**: 콜리전 복잡도, 내비 타일 수.
- **Tick 그룹/병렬화**: `stat game`, `stat physics`, `stat navmesh`.

### 7.7 프로파일링 도구

| 도구 | 용도 | 명령/경로 |
| --- | --- | --- |
| Unreal Insights | CPU/GPU/스트리밍/메모리 타임라인 | `Trace.Start/Stop`, `.utrace` |
| **Spatial Profiler(5.8 실험)** | 월드 파티션 셀 단위 스트리밍 재생 | Insights 탭, `WorldStreaming` 채널 |
| stat 명령 | 즉시 지표 | `stat unit`, `stat gpu`, `stat rhi`, `stat streaming`, `stat levels`, `stat sceneRendering` |
| ProfileGPU | 패스별 GPU 시간 | `ProfileGPU`, `r.ProfileGPU.TableFormatting` |
| GPU Visualizer | 프레임 그래프 | `Ctrl+Shift+,` |
| Hitch Snapshots(5.8) | 히치 시 트레이스+스크린샷 | `snapshothitches -start` |
| Memory Insights / Asset Size Map | 메모리 출처 | Insights Memory, Asset Audit |
| Chaos Visual Debugger | 물리 씬 복잡도 | CVD |

측정 규칙: **같은 동선·같은 시간대·같은 카메라**. 도보/달리기/탈것/비행 각각의 최악 구간을 정해 두고, 빌드마다 같은 지점을 측정한다. 5.8 `stat unit`은 VRAM Used/Budget을 보여주고, `stats.UnitTimestamp`로 프레임 번호·UTC를 남길 수 있다.

---

## 8. 단계별 제작 로드맵

각 Phase는 **통과 조건(gate)** 을 만족해야 다음으로 간다. 통과 조건은 숫자로 쓴다.

### Phase 0 — 프리프로덕션: 규모와 예산 (1~2주)

- 월드 크기, 이동 수단(도보/탈것/비행), POI 수, 타깃 기기, 프레임 목표를 문서화.
- 셀/로딩 반경/HLOD 계층/RVT 해상도를 9장 계산기로 확정.
- vertical slice용 셀 1~2개를 정한다(가장 밀도 높은 지역 + 가장 넓은 조망 지점).
- **Gate**: 예산표 작성, 셀당 데이터/메모리/로딩 시간 목표 설정, 측정 동선 정의.

### Phase 1 — 그레이박스/블록아웃 (2~4주)

- 지형 없이 평면/간단한 하이트맵으로 POI, 랜드마크, 동선을 배치.
- 이동 시간으로 거리 감각을 검증: 도보 1.4 m/s, 달리기 5~7 m/s, 탈것 15~30 m/s.
- 랜드마크 가시성(언덕 위, 강 건너, 멀리 보이는 탑)과 시야 차단(숲, 절벽)을 배치.
- **Gate**: 주요 POI 간 이동 시간이 의도한 리듬(예: 60~120초) 안. 빈 구간 없음. 셀 경계를 넘는 동선에서 끊김 없음.

### Phase 2 — 지형과 표면 (3~6주)

- 외부 DCC 침식 → 16-bit 하이트맵 → Landscape 임포트. Z scale/정밀도 검증.
- RVT 설정, 베이스 랜드스케이프 머티리얼(경사/고도 자동 블렌딩), 바이옴 마스크 레이어.
- 물/해안선, 주요 산맥·계곡의 실루엣 확정.
- **Gate**: 타일 심 없음. 근접 표면 디테일 확보(RVT 2 m/texel 이하 + 근접 텍스처 레이어). RVT 풀 eviction 없음. 지형 콜리전으로 도보 이동 가능. 원경 실루엣이 컨셉과 일치.

### Phase 3 — 스트리밍과 공간 구조 (2~4주)

- World Partition 그리드/로딩 반경 확정. OFPA 전환, Data Layer 분리.
- HLOD 2단 빌드, Lumen Far Field 연결, HLOD 빌드 CI.
- 패스트 트래블/컷신용 Streaming Source.
- **Gate**: 최악 동선에서 스트리밍 히치 0(또는 임계 이하). 셀 경계에서 팝 없음. 텔레포트 시 빈 셀 없음. HLOD 빌드 시간이 야간 빌드에 들어감.

### Phase 4 — PCG와 식생 (4~8주)

- 바이옴 규칙 확정, PCG 그래프 작성, 밀도/종 분포 튜닝.
- HISM/Nanite Foliage 선택, 바람, 그림자 예산.
- 수동 아트 디렉팅(랜드마크 주변, POI 접근로).
- **Gate**: 화면 내 인스턴스/오버드로 예산 내. 원경 숲이 비지 않음. PCG 재생성이 결정적. 수동 편집이 상위 파라미터 변경에도 유지.

### Phase 5 — 라이팅·대기·사운드 (2~4주)

- Sky Atmosphere/Cloud/Fog 기준 시간대 고정. Lumen/VSM 프로파일.
- 시간대 순환, 밤 조명, 실내/동굴 라이팅.
- 앰비언스/리버브 존, 바람/물 소리.
- **Gate**: 낮/밤/일출/일몰 4개 시간대에서 프레임 목표 유지. 밤 마을에서 그림자/라이팅 비용 예산 내. 노출 전환에서 멍해짐 없음.

### Phase 6 — 콘텐츠 밀도와 디테일 (지속)

- POI 내부, 도로/수계 인프라, 랜드마크 아트, 데칼/소품.
- 컬링/HLOD/스트리밍 재측정하며 밀도 상한 유지.
- **Gate**: 각 POI가 "도착-탐험-출발" 루프를 가짐. 셀당 데이터 예산 초과 없음.

### Phase 7 — 최적화·패키징·QA (4주+)

- cooked 빌드에서 스트리밍/RVT/PCG/HLOD 검증.
- 기기 프로파일별 스케일러빌리티, 메모리 캡, 로딩 시간.
- 히치 스냅샷 수집, 최악 동선 재현, 회귀 자동화.
- **Gate**: 타깃 기기에서 프레임/메모리/로딩 목표 달성. 크래시·누수 0. QA 동선 전체에서 스트리밍 실패 0.

---

## 9. 계산기와 체크리스트 사용법

`pipeline/open_world_helper.py`는 위 공식들을 코드로 고정한다. 외부 의존성이 없고, 테스트 66개가 숫자를 검증한다.

### 9.1 그리드/스트리밍

```bash
python pipeline/open_world_helper.py grid \
  --world-km 8 --cell-m 256 --loading-range-m 768 \
  --bytes-per-cell 30000000 --speed-mps 6
```

```
월드 8,000 m  |  셀 256 m  |  로딩 반경 768 m
  그리드            32 x 32 = 1,024 셀
  동시 로드 셀      최대 45개 (7x7 정사각형의 모서리 제외)
  월드 대비         4.39%
  셀 통과 시간      42.7 s  (분당 1.4 셀, 6 m/s)
  로드 윈도우       106.7 s
  셀 데이터         28.6 MB  -> 필요 처리량 0.3 MB/s
  상주 추정         1,287 MB
```

`--bytes-per-cell`을 주면 스트리밍 처리량과 상주 메모리를 함께 계산한다. `--json`으로 기계 판독 출력.

### 9.2 랜드스케이프

```bash
python pipeline/open_world_helper.py landscape --target-m 4000 --spacing-m 1.0
```

```
목표 4,000 m  |  4033x4033 정점  (4,000 m, 0.99 m 간격)
  타일              1x1
  섹션/컴포넌트     63 쿼드 x 4 섹션 = 126 쿼드
  컴포넌트          32x32 = 1,024개
  드로우콜(섹션)    최대 4,096
  Z scale           100.00  (높이 범위 512 m)
  높이 정밀도       1.04 cm
  하이트맵          32.5 MB (16-bit raw)
```

- `--target-m 8200`처럼 8,129 정점을 넘으면 2×2 타일로 나누고 경고를 낸다.
- `--height-range-m 2000`으로 Z scale을 계산한다.
- `--full-resolution`은 16-bit 전 범위 사용(Houdini의 Use Full Resolution).

### 9.3 RVT

```bash
python pipeline/open_world_helper.py rvt \
  --world-m 8129 --texels-per-m 0.5 --layout base_color_normal --tile-size 256
```

```
월드 8,129 m  |  타일 256 texel  |  최대 64 타일/축
  해상도            4096x4096 (16x16 타일)
  실제 밀도         0.504 texel/m (1.98 m/texel)
  텍셀당 바이트     1.5 B
  Mip0 메모리       24.0 MB
  전체 밉 포함      32.0 MB
  페이지 테이블     1.3 KB (341 타일)
  풀 추정           8.4 MB (mip0의 일부만 상주한다는 가정)
```

- `--layout`으로 BaseColor만(0.5 B) / +Normal(1.5 B) / +Mask(2.5 B)를 선택.
- `--uncompressed`는 디버깅용. 메모리가 4~8배.
- 풀 추정은 mip0의 35% 상주 가정이다. 실제 값은 `stat virtualtexturememory`로 확정한다.

### 9.4 HLOD

```bash
python pipeline/open_world_helper.py hlod --world-km 8
```

```
HLOD0    simplified_mesh  셀    512 m  반경   1024 m  ->     256 액터 (동시  21), 월드 셀당 4개, 빌드 ~6분
HLOD1    instancing       셀   2048 m  반경   4096 m  ->      16 액터 (동시  21), 월드 셀당 64개, 빌드 ~0분
합계: 272 프록시 액터, 전체 빌드 ~0.1시간(1코어 기준)
```

- `--layer NAME:TYPE:CELL_M:RANGE_M`로 레이어를 지정한다(여러 번 사용).
- 셀이 월드 셀의 배수가 아니면 경고, 로딩 반경이 셀 2개보다 작으면 팝 경고, 프록시가 5만 개를 넘으면 재빌드 경고.

### 9.5 체크리스트

```bash
python pipeline/open_world_helper.py checklist --print-default > world_status.json
# 항목 상태를 pass/fail/todo/skip으로 채운 뒤
python pipeline/open_world_helper.py checklist --status world_status.json
```

```
NOT READY  |  준비도 87.1%  (pass 31, fail 2, todo 3, skip 2 / 38)
  좌표계    pass  3  fail  0  todo  0  skip  0
  지형     pass  4  fail  1  todo  0  skip  0
  머티리얼   pass  4  fail  0  todo  0  skip  0
  스트리밍   pass  5  fail  0  todo  0  skip  1
  PCG    pass  4  fail  1  todo  0  skip  0
  인프라    pass  2  fail  0  todo  0  skip  0
  라이팅    pass  3  fail  0  todo  1  skip  0
  최적화    pass  4  fail  0  todo  2  skip  0
  빌드     pass  2  fail  0  todo  0  skip  1
블로커:
  - terrain.seams (fail): 타일 경계와 심(seam) 제거
  - pcg.wind (fail): 식생 바람과 그림자
  - lighting.tod (todo): 시간대 순환
  - perf.hlod (todo): HLOD 레이어와 빌드 파이프라인
  - perf.trace (todo): Unreal Insights 트레이스
```

- 38개 항목, 9개 범주(좌표계/지형/머티리얼/스트리밍/PCG/인프라/라이팅/최적화/빌드).
- 가중치 합으로 준비도 점수를 계산하고, **필수 항목이 pass가 아니면 ready=False**.
- `--list-items`로 전체 항목 ID를 본다.
- JSON은 `{"items": {...}}` 또는 `{id: status}` 둘 다 허용.

### 9.6 공식 요약

| 계산 | 공식 |
| --- | --- |
| 셀 수 | ceil(월드/셀)² |
| 동시 로드 셀 | 반경 R에 일부라도 걸치는 셀 (원형, 모서리 제외) |
| 로딩 윈도우 | (R − c/2) / 속도 |
| 셀당 필요 처리량 | 셀 바이트 / 로딩 윈도우 |
| 상주 메모리 | 동시 로드 셀 × 셀 바이트 |
| Landscape 정점 | 컴포넌트 수 × 컴포넌트 쿼드 + 1 |
| Z scale | 높이 범위(m) × 100 / 512 |
| 높이 정밀도 | 높이 범위 / (65,536 × 사용 비율) |
| RVT 해상도 | 2^ceil(log2(필요 텍셀/타일)) × 타일 |
| RVT mip0 | 해상도² × 텍셀당 바이트 |
| RVT 전체 밉 | mip0 × 4/3 |
| HLOD 프록시 수 | ceil(월드/HLOD 셀)² |

---

## 10. 자주 터지는 지점

| 증상 | 흔한 원인 | 처치 |
| --- | --- | --- |
| 셀 경계에서 0.5~2초 멈춤 | 셀당 액터/텍스처 과다, GC, PSO | 셀 데이터 분할, GC 옵션, PSO 캐시, Fast Geometry Streaming |
| 원경이 갑자기 사라짐 | HLOD 로딩 반경 < 셀 2개, HLOD 미빌드 | HLOD 셀/반경 조정, 빌드 CI |
| 원경 반사/GI에 건물이 없음 | Lumen Far Field 미설정, HLOD1 없음 | `r.LumenScene.FarField=1`, HLOD1 빌드, 컬링 반경 일치 |
| 지형 색이 이어붙인 타일마다 다름 | 타일 경계 정점/마스크 불일치, RVT 볼륨 경계 | 경계 정점 공유, RVT 볼륨 겹침, `unreal_landscape_layer_min/max` 통일 |
| 지형이 카메라를 따라 물결침 | VHM LOD popping / RVT 밉 불일치 | VHM 대신 Nanite Tessellation, RVT 밉/풀 확인, 엔진 핫픽스 |
| 지면이 흐릿함 | RVT 텍셀 밀도 부족, Low Mips 제거, VT eviction | 밀도/타일 재계산, 풀 확대, Continuous Updates |
| 풀숲에서 프레임 폭락 | 오버드로, WPO, 그림자 | 카드 수/크기, 원경 WPO off, 그림자 off, cull distance |
| 밤 마을에서 GPU 폭발 | 그림자 광원 수, VSM 무효화, Lumen 노이즈 | MegaLights 예산, 그림자 거리, Lumen 품질, 광원 밀도 |
| 시간대 순환 시 그림자 깜빡임 | VSM 캐시 무효화, Sky Light 캡처 | 태양 이동 완만, 캡처 주기, Deferred Invalidation Budget |
| 메모리가 계속 증가 | PCG 런타임 생성 액터, 텍스처 풀, HLOD 프록시 | 생성/소멸 정책, 풀 고정, 프록시 스트리밍, Insights Memory |
| 88M km 근처에서 덜덜 떨림 | float 사용 시스템(Niagara, 서드파티, 셰이더) | 단정밀 시스템 목록화, 원점 근처로 이동, DF/카메라 상대 좌표 |
| HLOD 빌드가 밤새 안 끝남 | 프록시 수 과다, 병합/단순화 비용 | 셀 크기 확대, 레이어 단순화, Rebuild Policy(SSIM), 분산 빌드 |
| 에디터에서 월드가 비어 보임 | World Partition이 언로드 상태 | `Is Spatially Loaded`, Preview Grids, Data Layer 상태 확인 |
| 쿡에서만 RVT가 깨짐 | VT Fixed Pool 미설정, RVT 자산 누락 | cooked 풀 설정, 에셋 레퍼런스 확인, 패키지 로그 |

---

## 11. 참고 자료

**Epic 공식 문서 (UE 5.8 기준)**

- World Partition — https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition-in-unreal-engine
- World Partition HLOD — https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition---hierarchical-level-of-detail-in-unreal-engine
- PCG with World Partition — https://dev.epicgames.com/documentation/en-us/unreal-engine/using-pcg-with-world-partition-in-unreal-engine
- Landscape Technical Guide — https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide-in-unreal-engine
- Runtime Virtual Texturing — https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-virtual-texturing-in-unreal-engine
- Lumen Technical Details — https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-technical-details-in-unreal-engine
- Nanite — https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine
- Water Waves Asset — https://dev.epicgames.com/documentation/en-us/unreal-engine/simulating-waves-using-the-water-waves-asset-in-unreal-engine
- UE 5.8 Release Notes — https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-8-release-notes
- UE 5.7 Release Notes — https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-7-release-notes

**엔진 릴리스/성능 정리**

- Unreal Engine 5.8 Released (Epic 포럼, 2026-06-17) — Mesh Terrain, PCG, PVE, Lumen Lite, MegaLights
- Unreal Engine 5.8 Performance Highlights (Tom Looman, 2026-08) — Spatial Profiler, HLOD Rebuild Policy, Fast Geometry Streaming, VSM/Nanite 변경
- Unreal Engine 5.7 Released (Epic 포럼, 2025-11-12) — PCG 프로덕션 레디, Nanite Foliage, Substrate
- Large World Coordinates / 그래픽스 정밀도 (Graphics Programming Conference, Epic) — translated world space, double-float
- Lumen SIGGRAPH 2022 (Wright et al.) — Far Field, HLOD 기반 원경 GI

**DCC/파이프라인**

- Houdini Engine for Unreal: Landscapes — https://www.sidefx.com/docs/houdini/unreal/landscape/basics.html
- Houdini Engine: World Partition — https://www.sidefx.com/docs/houdini/unreal/worldpartition/worldpartition.html
- World Machine / Gaea 공식 문서 — 타일 빌드·r16 익스포트

**주의**: 문서의 수치(셀 크기, 해상도, 메모리)는 계획용 근사치다. 엔진 버전·플랫폼·콘텐츠에 따라 달라지므로, 9장 계산기로 초기값을 잡고 프로파일링으로 확정한다. 실험 기능의 상태는 핫픽스마다 바뀔 수 있으므로 릴리스 노트를 확인한다.
