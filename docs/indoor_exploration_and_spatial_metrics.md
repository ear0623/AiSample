# 인게임 실내 탐사 수치 설정과 공간 세부 묘사 가이드

> 대상: C++/그래픽스 배경으로 UE5에서 실내 탐사(폐가·연구소·던전·상업시설)를 직접 만드는 개발자
> 범위: **Part 1** 건물의 정밀 수치(플레이어·복도·문·층고·계단·가구·카메라 붐) → **Part 2** 공간 세부 묘사와 환경 스토리텔링 → **Part 3** 방 배치 토폴로지와 최적화
> 기준 시점: **2026-11. Unreal Engine 5.8** 기준. 엔진 기본값은 `ACharacter` / `UCharacterMovementComponent` / `USpringArmComponent` 소스 기준이다.
> 함께 읽는 문서: [오픈월드 콘텐츠·건축 설계 매뉴얼](open_world_content_and_architecture_guide.md)(모듈러 킷·루멘 누광·인간공학 7장) · [오픈월드 제작 파이프라인](open_world_creation_pipeline.md)(라이팅·HLOD) · [PBR 머티리얼 파이프라인](pbr_material_pipeline.md)(트림 시트·데칼)
> 함께 쓰는 코드: [`pipeline/indoor_metric_helper.py`](../pipeline/indoor_metric_helper.py) · [`tests/test_indoor_metrics.py`](../tests/test_indoor_metrics.py)

---

## 목차

**Part 1 — 정밀 수치 설정**

0. [한눈에: 실내는 "치수 → 카메라 → 조명 → 서사" 순서로 결정된다](#0-한눈에-실내는-치수--카메라--조명--서사-순서로-결정된다)
1. [단위와 좌표계](#1-단위와-좌표계)
2. [플레이어 기준 치수](#2-플레이어-기준-치수)
3. [복도와 통로](#3-복도와-통로)
4. [문과 개구부](#4-문과-개구부)
5. [천장과 층고](#5-천장과-층고)
6. [계단과 경사로](#6-계단과-경사로)
7. [가구·창문·엄폐물](#7-가구창문엄폐물)
8. [실내 카메라 붐(SpringArm) 최적화](#8-실내-카메라-붐springarm-최적화)
9. [수치 검증: metrics zoo와 자동 검사](#9-수치-검증-metrics-zoo와-자동-검사)

**Part 2 — 공간 세부 묘사와 환경 스토리텔링**

10. [시간의 4층위: 한 방에 역사를 쌓는 법](#10-시간의-4층위-한-방에-역사를-쌓는-법)
11. [단서 설계: 3단서 + 1질문](#11-단서-설계-3단서--1질문)
12. [밀도와 리듬: 방마다 이야기 하나](#12-밀도와-리듬-방마다-이야기-하나)
13. [시각적 길찾기와 프레이밍](#13-시각적-길찾기와-프레이밍)
14. [실내 조명 연출](#14-실내-조명-연출)
15. [촉각·청각 디테일](#15-촉각청각-디테일)
16. [서사 오브젝트의 기술 구현](#16-서사-오브젝트의-기술-구현)
17. [자주 하는 실패](#17-자주-하는-실패)

**Part 3 — 레이아웃 토폴로지와 최적화**

18. [방 배치 토폴로지](#18-방-배치-토폴로지)
19. [락앤키 그래프와 동선](#19-락앤키-그래프와-동선)
20. [소품 밀도 예산](#20-소품-밀도-예산)
21. [방 단위 오클루전·컬링·수면](#21-방-단위-오클루전컬링수면)
22. [예산표와 프로파일링](#22-예산표와-프로파일링)
23. [자주 터지는 지점](#23-자주-터지는-지점)
24. [참고 자료](#24-참고-자료)

---

## 0. 한눈에: 실내는 "치수 → 카메라 → 조명 → 서사" 순서로 결정된다

실내 탐사 레벨이 무너지는 순서는 정해져 있다. 대개 조명과 소품을 먼저 넣고, 마지막에 "카메라가 벽을 뚫는다"는 걸 발견한다. 그때는 벽을 옮길 수 없으므로 카메라를 억지로 접고, 화면이 캐릭터 등짝으로 가득 차고, 결국 그 방을 지운다. 순서를 뒤집으면 비용이 1/10로 줄어든다.

```
① 치수      플레이어 캡슐·눈높이·보폭을 먼저 고정한다          (사실, 바꾸면 전체가 흔들림)
② 카메라    그 치수에서 카메라가 숨 쉴 공간을 계산한다          (계산, 문서 8장)
③ 조명      공간의 시야와 무드를 정한다                        (연출)
④ 서사      그 공간에 누가 살았고 무슨 일이 있었는지 쌓는다     (연출)
⑤ 최적화    방 단위로 로드·틱·라이트를 끊는다                  (측정)
```

### 0.1 실외와 실내가 갈리는 네 지점

| 항목 | 실외 | 실내 | 결과 |
| --- | --- | --- | --- |
| 여유 공간 | 수백 m | 벽까지 1~3 m | 카메라 붐이 상시 충돌한다 |
| 시야 | 지평선까지 열림 | 문·모서리로 잘림 | 오클루전이 아군이자 적 |
| 광원 | 태양 1개 + 스카이 | 방마다 3~10개 | 그림자·VSM 페이지가 병목 |
| 플레이어 이동 | 달리기·점프·차량 | 걷기·웅크리기·문 열기 | 속도·카메라 감도가 달라져야 한다 |

실내에서 가장 흔한 착각은 "실외에서 잘 돌아간 300 cm 복도를 그대로 쓰면 된다"이다. 산술적으로는 통과하지만, 3인칭 카메라는 폭이 아니라 **벽까지의 거리**로 판정되므로 300 cm도 부족할 수 있다(8장의 식). 반대로 1인칭이라면 150 cm 복도가 오히려 긴장감을 만든다. **시점(point of view)이 치수를 결정하고, 치수가 공간의 성격을 결정한다.**

### 0.2 숫자를 세 층으로 나눈다

| 층 | 예 | 성격 | 바꾸는 비용 |
| --- | --- | --- | --- |
| 플레이어 사실 | 캡슐 반경 34, 눈높이 152, 보폭 60 | 엔진·물리에서 측정되는 사실 | 전 레벨 재작업 |
| 건축 관습 | 복도 180, 문 120, 층고 300 | 프로젝트가 정한 규약 | 킷·모듈 재작업 |
| 연출 취향 | 천장 260(압박), 복도 400(웅장), 문 90(불편) | 의도된 일탈 | 국소 수정 |

레벨 디자인에서 말하는 **metrics**는 이 세 층을 구분하는 데서 시작한다. 플레이어 치수는 "측정되는 사실"이고, 복도 폭은 "정한 규약"이며, 일탈은 "규약이 있을 때만 읽힌다"([The Level Design Book, Metrics](https://book.leveldesignbook.com/process/blockout/metrics)). 규약 없는 일탈은 그냥 실수로 보인다.

### 0.3 착수 전에 고정할 실내 규약표

프로젝트 시작 시 아래 표를 채워 `docs/`에 커밋하고, 이후 모든 방은 이 표를 기준으로 만든다. 빈칸이 있으면 200번째 방에서 반드시 다르게 만든다.

| 항목 | 값 | 근거/비고 |
| --- | --- | --- |
| 시점 | 3인칭 / 1인칭 / 전환 | 카메라 계산이 완전히 달라진다 |
| 캡슐 | 반경 ___ / 전고 ___ / 웅크리기 ___ | 2장 |
| 눈높이 | 1인칭 ___ / 3인칭 피벗 ___ | 2장 |
| 복도 | 최소 ___ / 기본 ___ / 교행 ___ | 3장 |
| 문 | 싱글 ___ x ___ / 더블 ___ | 4장 |
| 천장 / 층고 | ___ / ___ (슬래브 ___) | 5장 |
| 계단 | 단높이 ___ / 디딤판 ___ / 폭 ___ / 계단참 ___ | 6장 |
| 그리드 | ___ cm (보통 100 / 200 / 400) | 모듈러 킷 정합 |
| 카메라 암 | 실외 ___ / 실내 ___ / 최소 ___ | 8장 |
| 방 등급 | A(핵심) / B(통과) / C(배경) 와 소품 예산 | 20장 |
| 조명 예산 | 방당 동적 광원 ___ 개, 그림자 광원 ___ 개 | 14장 |

---

# Part 1 — 정밀 수치 설정

## 1. 단위와 좌표계

- **1 uu = 1 cm.** UE5의 기본 단위이며, 문서·코드·에디터가 모두 같은 단위를 쓴다. 180 cm 문은 `180.0`이다.
- **그리드.** 실내는 100 cm 격자가 기본, 가구·소품은 25/50 cm 보조 격자를 쓴다. 모듈러 킷은 200/400 cm 배수로 올리는 편이 벽 두께·문 위치를 맞추기 쉽다([오픈월드 콘텐츠 가이드 8장](open_world_content_and_architecture_guide.md)).
- **원점.** 건물은 자기 원점(건물 루트)을 갖고, 실내 메시는 그 원점 근처에서 만든다. 월드 원점에서 100 km 떨어진 곳에 있는 건물의 버텍스는 단정밀도에서 1 cm 이하 오차가 누적되어 벽 틈이 벌어진다(LWC는 월드 좌표를 double로 올렸지만 버텍스는 여전히 float다).
- **좌표 관례.** X = 정면, Y = 오른쪽, Z = 위. 문은 Z축 기준 높이, 복도는 진행축 기준 폭으로 이야기한다.

---

## 2. 플레이어 기준 치수

### 2.1 엔진 기본값을 먼저 정확히 읽는다

| 항목 | UE 기본값 | 실제 성인 | 차이의 이유 |
| --- | --- | --- | --- |
| 캡슐 반경 | 34 cm | 어깨 반폭 23 cm | 충돌 안정성. 좁으면 모서리에 끼고 계단에서 떨린다 |
| 캡슐 전고 | 176 cm (반높이 88) | 170~175 cm | 점프·계단 여유. 모델보다 5~10 cm 크다 |
| 눈높이 | 152 cm (반높이 88 + `BaseEyeHeight` 64) | 155~165 cm | 카메라가 목·가슴에 있다. 대부분의 FPS가 이렇게 한다 |
| 웅크리기 전고 | **80 cm** (`CrouchedHalfHeight` 40) | 110~130 cm | 엔진 기본값이 실제보다 낮다. 그대로 쓰면 기어가는 느낌 |
| 보폭(걸음) | — | 60~66 cm | 계단 2R+T의 기준값(6장) |
| 점유 폭(팔 포함) | 캡슐 68 cm | 60 cm | 게임 캡슐이 더 넓다 |
| 이동 속도 | `MaxWalkSpeed` 600 uu/s = 6 m/s | 걷기 1.4 m/s, 달리기 4~6 m/s | 600은 **달리기** 속도다. 실내 걷기는 250~350으로 낮춘다 |

```cpp
// 실내 탐사용 캐릭터 기본값 (ACharacter 생성자)
GetCapsuleComponent()->InitCapsuleSize(34.f, 88.f);   // 68 x 176
BaseEyeHeight = 64.f;                                  // 눈높이 152
GetCharacterMovement()->SetCrouchedHalfHeight(52.f);   // 웅크리기 전고 104 cm
GetCharacterMovement()->MaxWalkSpeed = 320.f;          // 실내 걷기 3.2 m/s
GetCharacterMovement()->MaxWalkSpeedCrouched = 170.f;
GetCharacterMovement()->MaxStepHeight = 45.f;          // 엔진 기본 유지
```

주의: `CrouchedHalfHeight`는 UE 5.0에서 직접 멤버 접근이 deprecated가 되어 `SetCrouchedHalfHeight()`를 쓴다. 또한 웅크리기 상태의 눈높이는 `ACharacter::CrouchedEyeHeight`로 따로 관리되며, 실제 눈높이는 `반높이 + CrouchedEyeHeight`다(기본 32 -> 84 cm). 전고 104에서 눈높이 100을 원하면 `CrouchedEyeHeight`를 48로 둔다. 캡슐만 키우고 눈높이를 그대로 두면 "몸은 일어섰는데 시야는 바닥"이 된다.

### 2.2 왜 실제 치수를 그대로 쓰면 안 되는가

1. **캡슐은 몸이 아니라 물리 도형이다.** 캡슐 반경 34는 어깨(23)보다 11 cm 크다. 이 여유가 없으면 캐릭터가 벽 모서리에 걸리고, 계단·경사에서 미끄러지고, 좁은 문에서 진동한다.
2. **눈높이는 실제 눈보다 낮다.** 카메라를 실제 눈높이(163)에 두면 176 캡슐의 정수리와 시야가 너무 가까워져 위를 볼 때 머리통이 화면에 걸린다. 152~160이 안전하다. 1인칭에서 손·무기를 화면에 띄운다면 150~158이 자연스럽다.
3. **웅크리기는 반대로 높여야 한다.** 기본 80 cm는 "네 발로 기는" 높이다. 100~110 cm로 올리면 ① 로우 커버 뒤에 앉은 자세가 자연스럽고 ② 덕트·책상 밑 통과가 납득되며 ③ 3인칭 카메라가 캐릭터를 잃지 않는다.
4. **속도는 공간의 크기를 바꾼다.** 6 m/s로 180 cm 복도를 지나면 시야가 0.3초 만에 지나가 버려 공간을 읽을 수 없다. 실내는 걷기 300 내외, 웅크리기 150 내외가 적당하다. 같은 방이라도 속도가 절반이면 두 배로 넓게 느껴진다.

### 2.3 시점별 차이

| | 1인칭 | 3인칭(오버 더 숄더) | 3인칭(자유 붐) |
| --- | --- | --- | --- |
| 눈높이 | 158~166 | 피벗 145~155, 카메라 175~195 | 피벗 140~150 |
| 필요 복도 폭 | 150 이상 | 180~220 | 240 이상(권장 300) |
| 최소 천장 | 240 | 280 | 300 |
| 문 폭 | 110~130 | 120~150 | 150 이상 |
| 실내 적합성 | 폐가·호러·긴장 | 액션·탐사 | 넓은 실내·홀 |

3인칭이 기본이라면 아래 8장을 먼저 읽고 복도 폭을 정한다. 1인칭이 기본이면 3장의 최소값을 쓰고, 카메라 충돌은 벽에 붙었을 때의 근접 클리핑만 신경 쓰면 된다(카메라 액터에 작은 구체 트레이스).

---

## 3. 복도와 통로

### 3.1 표준 폭

| 용도 | 폭 | 설명 |
| --- | --- | --- |
| 1인 통과 최소 | 120~150 cm | 실제 건축 복도 법규 하한이 120. 게임에서는 150 미만이면 벽이 계속 시야를 때린다 |
| 탐사 기본 | 180~220 cm | 3인칭 카메라가 좌우 20~25도 회전할 여유. 문 하나 지나고 나서 숨 쉴 공간 |
| 2인 교행·NPC 통행 | 240~280 cm | 두 캐릭터(60+60) + 사이 60 + 소품 여유 |
| 전투·양방향 교전 | 300~400 cm | 엄폐물을 놓고도 동선이 남는 폭 |
| 대형 홀 연결 | 400 cm 이상 | 카메라가 전방위로 돌 수 있는 최소선(8.2절) |

실제 건축 기준도 같은 방향을 가리킨다. 영국·미국 주택의 복도는 90~120 cm지만, 게임 엔진 권장치는 Unreal 150 cm, Unity 200 cm이며 "플레이어 폭의 최소 두 배"를 요구한다([LDB Metrics](https://book.leveldesignbook.com/process/blockout/metrics)). **최소 두 배**라는 말은 캡슐 68의 두 배인 136을 뜻하고, 여기에 카메라·소품 여유를 더해 180이 나온다.

### 3.2 폭을 정하는 네 가지 제약

복도 폭은 취향이 아니라 아래 네 개의 최댓값으로 결정된다.

```
W ≥ 2 × (캡슐 반경 + 여유 10)                    … 통과 (68 + 20 = 88)
W ≥ 2 × (에이전트 반경 + 셀 크기)              … 내비메시 생성 (106)
W ≥ 2 × (숄더 오프셋 + L·cosφ + probe)           … 카메라 전방위 회전 (8.2절)
W ≥ 2 × 점유 폭 + 60                             … 2인 교행 (180)
```

Recast 내비메시는 에이전트 반경(기본 34)에 셀 크기(기본 19)만큼 폴리곤을 깎는다. 유효 폭이 110 cm 아래로 내려가면(계산값 106에 여유를 둔 값) 내비 폴리곤이 끊겨 NPC가 문 앞에서 멈추는 일이 생긴다. 좁은 폐가를 만들면서 NPC를 넣는다면 `RecastNavMesh`의 에이전트 반경을 25~30으로 낮추고, 셀 크기를 15로 줄여 다시 빌드해 본다(비용은 빌드 시간과 메모리).

### 3.3 복도 단면의 여유

폭만 맞추면 절반이다. 단면에서 아래 세 가지를 함께 본다.

| 위치 | 여유 | 이유 |
| --- | --- | --- |
| 벽~어깨 | 좌우 각 25 cm 이상 | 액자·배관·문손잡이·에어컨 실내기가 통행을 방해하지 않게 |
| 머리~천장 | 60 cm 이상 | 카메라 상향·점프·계단 위 문 |
| 바닥~가방/소품 | 40 cm 이상 | 발에 채이는 잔해가 이동을 막지 않게(의도된 장애물은 예외) |

복도에 소품을 놓을 때는 **한쪽 벽에만** 놓는다. 양쪽에 놓으면 시각적으로도 막히고, 카메라가 지나갈 때 양쪽에서 동시에 충돌해 암이 요동친다. 소품이 많은 구간은 폭을 40 cm 넓히거나, 소품을 벽감(alcove) 안으로 밀어 넣는다.

### 3.4 복도 길이와 리듬

- 한 구간(직선)은 **8~15 m**가 적당하다. 20 m를 넘으면 지루해지고, 문이 안 보여 "여기가 어디인지"를 잃는다.
- 15 m마다 **시각적 사건**을 하나 넣는다: 창, 꺾임, 계단, 문, 바닥 재질 변화, 라이트 색 변화.
- 꺾임은 90도보다 **완만한 각(15~30도)**이 시야를 길게 만들어 준다. 90도 코너는 다음 공간을 완전히 숨기지만, 30도는 "무언가 보인다"를 남긴다(13장 프레이밍).

---

## 4. 문과 개구부

### 4.1 왜 실제 90 cm 문이 게임에서 안 되는가

실제 주거 문은 90 cm(미국 36인치, 한국 0.9 m)다. 캡슐 지름이 68이므로 **좌우 여유가 각 11 cm**밖에 없다.

| 문제 | 원인 | 증상 |
| --- | --- | --- |
| 문틀에 걸림 | 캡슐 68 + 문틀 충돌 두께 | 달리며 들어가면 모서리에 걸려 속도가 0이 된다 |
| 카메라 점프 | SpringArm probe 12가 문틀에 닿음 | 문을 지날 때 화면이 캐릭터 등으로 확 당긴다 |
| 문 leaf 충돌 | 여닫이 문짝이 열리는 공간을 먹음 | 반쯤 열린 문은 유효 폭을 30~50 cm 줄여 캡슐이 걸린다 |
| 상호작용 실패 | 문 손잡이 위치와 캡슐 | 손이 문틀에 가려 프롬프트가 안 뜬다 |

### 4.2 표준 개구부

| 종류 | 폭 | 높이 | 비고 |
| --- | --- | --- | --- |
| 싱글 도어(탐사 기본) | 120~150 cm | 220~250 cm | 120이 하한, 130~140이 무난 |
| 더블 도어 | 200~240 cm | 230~260 cm | 양쪽 leaf 각 100~120 |
| 아치형 개구부 | 180~300 cm | 240~320 cm | 프레임 없음. 카메라 충돌은 벽으로 처리 |
| 차고/셔터 | 300~400 cm | 250~350 cm | 문 상단에 롤러 박스 300~400 깊이 |
| 창문 | 80~160 cm | 창대 80~100, 상단 200~220 | 7장 |

참고로 실제 게임 제작 현장의 권장치도 이 범위다. Unreal 기준 문 110 x 220, 영국 게임 회사(Arma Reforger) 기준 일반 건물 125 x 237, 예외 90 x 200이다([BIS 환경 지표](https://community.bistudio.com/wiki/Arma_Reforger:Environment_Metrics)). **90은 "예외 건물"의 수치**이고, 탐사 기본값으로 쓰면 매번 문제가 된다.

### 4.3 문 하나에 필요한 여섯 개의 수치

```
문 폭        W_d  ≥ 캡슐 지름(68) + 40      -> 108 이상 (권장 118)
문 높이      H_d  ≥ 캡슐 전고(176) + 40     -> 216 이상 (계단 위 문은 +단높이)
문틀 두께    T_f  4~8 cm (충돌은 벽 두께와 동일하게)
문턱 높이    h_t  0~2 cm (넘으면 MaxStepHeight 소모, 3 cm 이상은 시각적 걸림)
손잡이 높이  100~110 cm (양쪽), 문 두께만큼 안쪽
개폐 여유     문짝 폭 + 10 cm (문이 열리는 쪽에 가구를 두지 않는다)
```

### 4.4 90 cm 문을 꼭 써야 할 때

폐가·병원처럼 좁은 문이 분위기의 핵심이라면, 폭을 포기하는 대신 아래를 함께 쓴다.

1. **문틀 충돌을 Camera 채널에서 Ignore로.** 벽은 Camera를 Block하지만 문틀·문짝은 Ignore. `ProbeChannel`을 `Camera`로 두고, 문틀 메시의 콜리전 프로파일에서 Camera 응답만 Ignore로 만든다. 카메라가 문틀을 통과해도 시각적으로는 문 안쪽이 보이므로 티가 적다.
2. **문 통과 트리거에서 암을 140으로 단축.** 문 앞 120 cm 지점에 트리거 볼륨을 두고, 진입 시 0.15초에 걸쳐 암을 줄이고 나가면 복원한다(8.3절 코드).
3. **문짝은 열린 상태로 고정.** 여닫이 애니메이션을 넣더라도 게임플레이 중에는 90도 이상 열린 상태를 유지한다. 닫힌 문을 플레이어가 열게 하려면 문틀 폭을 140으로 늘린다.
4. **문 앞 30 cm를 비운다.** 문 양옆에 가구·벽감을 두지 않아 접근 각도를 확보한다.

---

## 5. 천장과 층고

### 5.1 천장 높이 표

| 용도 | 실제 건축 | 게임 권장 | 비고 |
| --- | --- | --- | --- |
| 주거(폐가·아파트) | 240~270 | **280~320** | 3인칭 카메라 상향 여유. 260은 압박 연출용 |
| 오피스·연구소 | 270~300(반자 포함 400+) | **360~450** | 설비·덕트가 노출되면 450 |
| 상업시설 | 300~450 | **400~600** | 아트리움은 800+ |
| 던전·벙커 | 250~350 | **320~400** | 낮은 천장은 의도된 공포. 260 이하는 1인칭에서만 |
| 산업·창고 | 600~1200 | 실제값 유지 | 크레인·랙 높이 기준 |
| 대형 홀 | 800+ | 800~1500 | 카메라 암을 400까지 늘려도 된다 |

실제 건축에서도 천장고는 용도로 갈린다. Arma Reforger의 지표는 일반 건물 270~330, 예외 220 이상이고, 벽 두께 30~50 cm, 내벽 20 cm를 함께 규정한다. 게임 권장치가 실제보다 10~30% 높은 이유는 **카메라**와 **시야** 때문이다.

### 5.2 카메라가 요구하는 천장 높이

3인칭 카메라는 아래를 내려다보므로 피벗보다 위로 올라간다. 위를 볼 때는 반대로 내려간다.

```
필요 천장 ≥ 눈높이 + L·sin(φ) + probe          (내려다보는 피치 φ)
아래를 볼 때 필요 바닥 ≥ 눈높이 - L·sin|φ| + probe
```

예: 눈높이 152, 암 220, 피치 15도 → 152 + 57 + 12 = **221 cm**. 천장 300이면 79 cm 여유가 남고, 250이면 암이 216까지 줄어든다. 계단을 오르며 위층을 올려다보는 순간이 실내 카메라 사고의 절반이므로, **계단참 위 천장은 260 이상** 확보한다.

### 5.3 층고(floor-to-floor)는 천장고가 아니다

```
층고 = 천장고 + 슬래브(20~30) + 마감(5~10) + (오피스) 설비 30~50
```

| 용도 | 천장고 | 층고 | 계단 단수(17.5 기준) |
| --- | --- | --- | --- |
| 주거 | 300 | 320~340 | 18~19 |
| 오피스 | 400 | 430~480 | 25~27 |
| 상업 | 450 | 480~550 | 27~31 |
| 던전 | 350 | 400 | 23 |

층고는 계단 단수·계단실 크기·엘리베이터 정격과 연결된다. 방을 먼저 만들고 층고를 나중에 정하면 계단이 계단실을 뚫고 나온다(6.4절).

### 5.4 낮은 천장을 쓰는 법

낮은 천장은 훌륭한 연출 도구다. 다만 **시점에 따라 허용치가 다르다.**

| 시점 | 허용 최저 | 연출 |
| --- | --- | --- |
| 1인칭 | 230 | 지하 통로, 덕트, 관 속. 손전등과 함께 |
| 3인칭 | 270 | 폐가 2층, 다락. 카메라 암을 160으로 줄일 것 |
| 3인칭 자유 붐 | 300 | 그 아래는 카메라가 천장을 뚫는다 |

---

## 6. 계단과 경사로

### 6.1 세 개의 기준을 동시에 만족시킨다

| 기준 | 식/값 | 의미 |
| --- | --- | --- |
| Blondel 보폭 비 | `2R + T = 60~66 cm` (이상 63) | 걸음 리듬. 17/29가 이상값 |
| 한국 건축법 | 단높이 ≤18, 단너비 ≥24 (주택 26) | 법규 하한. 게임에서도 "급해 보이지 않는" 선 |
| CMC 경사 한계 | `WalkableFloorAngle 44.765°` (cos 0.71) | 캐릭터가 걸어 오를 수 있는 최대 경사 |

표준 계단 18/28은 `2R+T = 64`, 경사 `atan(18/28) = 32.7°`로 셋을 모두 만족한다. 반면 21/21은 `2R+T = 63`으로 Blondel은 통과하지만, 경사 45°로 CMC 한계(44.765°)를 넘고 법규 단높이도 위반한다. **Blondel만 보면 45° 계단이 합격한다**는 것이 이 표의 핵심이다.

### 6.2 계단 제원표

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 단높이(R) | 15~18 cm | 18 초과는 법규 위반, 20 이상은 사다리 |
| 디딤판(T) | 26~32 cm | 24 미만은 발이 걸린다 |
| 계단 폭 | 140~180 cm | 법규 120. 2인 교행·카메라는 140 이상 |
| 계단참 깊이 | 140 cm 이상 | 12~16단마다. 법규는 3 m 높이마다 |
| 계단참 폭 | 계단 폭과 동일 | 법규 유효너비 120 이상 |
| 계단 유효 높이 | 210 cm 이상 | 법규. 3인칭은 +암 수직 성분 |
| 난간 높이 | 110~120 cm | 법규 120(옥내 90 허용). 게임은 110이 시야를 덜 가린다 |
| 손잡이 높이 | 85 cm | 법규. 계단 경사와 평행 |
| 난간 간살 | 10 cm 이하 | 법규. 어린이 머리 끼임 방지 |

### 6.3 콜리전을 어떻게 줄 것인가

계단의 **시각 메시**와 **콜리전**은 다르게 준다. 선택지는 세 가지다.

| 방식 | 구성 | 장점 | 단점 |
| --- | --- | --- | --- |
| 경사 램프 콜리전 | 계단 전체에 32.7° 경사면 하나 | 싸고 부드럽다. 캐릭터가 튀지 않는다 | 발이 단에 닿지 않아 "미끄러지는" 느낌. 단이 높으면(>45°) 불가 |
| 단별 콜리전 | 각 단에 박스 | 정확하다. 발소리·카메라 흔들림이 자연스럽다 | 콜리전 수 증가, 단 경계에서 미세한 튐 |
| 혼합 | 시각은 단, 콜리전은 램프 + 단 앞턱만 | 대부분의 상용 게임 | 케이지·울타리와의 충돌 정합 필요 |

`MaxStepHeight`가 45이므로 18 cm 단은 자동으로 올라간다. 하지만 **2단(36)까지는 오르고 3단(54)은 못 오른다**는 점을 기억한다. 계단을 3단씩 묶은 "계단 블록" 메시를 쓰면 캐릭터가 중간에서 멈춘다.

```cpp
// 계단용 콜리전 프로파일을 따로 두고, 시각 메시와 분리한다
StairMesh->SetCollisionProfileName(TEXT("BlockAll"));
StairCollision->SetCollisionProfileName(TEXT("BlockAllDynamic"));
// 카메라는 계단 난간을 통과해도 된다 (좁은 계단실에서 암이 요동치지 않게)
StairRail->SetCollisionResponseToChannel(ECC_Camera, ECR_Ignore);
```

### 6.4 층고에서 계단을 역산한다

```
단수 n = ceil(층고 / R)
실제 단높이 R' = 층고 / n          (반드시 균등. 마지막 단만 다르면 캐릭터가 걸린다)
수평 길이 = n × T
계단실 길이 = 수평 길이 + 계단참 깊이 × (계단참 수) + 60(진입 여유)
```

예: 층고 320, R 18 → n=18, R'=17.78, 수평 504, 계단참 1개 → 계단실 길이 약 704 cm. 3.2 m 층고 건물에서 계단실이 7 m를 먹는다는 것을 알고 평면을 잡아야 한다. 계단실을 코어에 넣을지, 방 사이에 끼울지가 여기서 결정된다.

### 6.5 경사로와 특수 이동

| 종류 | 경사/치수 | 비고 |
| --- | --- | --- |
| 장애인 경사로 | 1:12 (4.8°) | 법규 1:8(7.1°)이 최대. 게임에서는 1:8까지 |
| 차량 램프 | 1:8~1:10 | 지하 주차장 |
| 사다리 | 단높이 30~35, 폭 50 | 걸어서 못 오른다. 상호작용 이동으로 |
| 돌음(나선) 계단 | 단너비 30 지점 기준 | 캡슐이 못 들어가므로 폭 200 이상 또는 이동 애니메이션 |

`WalkableFloorAngle`을 44.765에서 올리면(예: 55) 캐릭터가 벽에 붙어 걸어 올라가는 버그가 생긴다. 경사로는 40° 이하로 유지하고, 그 이상은 상호작용·점프·사다리로 처리한다.

---

## 7. 가구·창문·엄폐물

### 7.1 가구 치수(실제값을 그대로 쓴다)

| 가구 | 높이 | 폭/깊이 | 비고 |
| --- | --- | --- | --- |
| 책상 | 72~75 | 120~180 x 60~80 | 사무용 74 |
| 식탁 | 72~75 | 4인 120 x 80 | |
| 의자 좌면 | 42~45 | 45 x 45 | 등받이 85~95 |
| 소파 좌면 | 40~45 | 1인 80, 3인 200 | 팔걸이 60~65 |
| 침대(매트리스 상면) | 50~55 | 싱글 100 x 200, 더블 150 x 200 | |
| 수납장/책장 | 180~210 | 80~120 x 35~45 | 210 이상은 사다리 필요 |
| 주방 상판 | 85~90 | 60 깊이 | |
| 냉장고 | 170~190 | 60~70 | |
| 화장실 변기 | 40 | 38 x 70 | |
| 세면대 | 80~85 | 60 x 45 | |

가구는 **실제 치수를 쓰는 것이 가장 빠르다.** 가구만 실제 비율이면 방이 조금 커도 "사람이 사는 공간"으로 읽힌다. 반대로 가구를 10% 키우면 방이 갑자기 좁아 보인다.

### 7.2 창문

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 창대 높이 | 80~100 cm | 100 이상이면 밖을 못 본다. 80이면 앉아서 내다봄 |
| 창 상단 | 200~220 cm | 천장 300이면 상인방 80 |
| 창 폭 | 80~160(1짝), 200~300(3짝) | |
| 창틀 두께 | 8~15 cm | 빛이 새는 틈의 원인 |
| 커튼박스 | 15 x 15 | |

창문은 실내 조명의 **주광원**이다. 창 하나의 크기가 방의 밝기와 그림자 방향을 결정하므로, 방을 만들 때 창 위치를 먼저 정하고 가구를 배치한다(14장). 3인칭 카메라는 창 밖으로 나가려 하므로, 창에 `Block` 콜리전을 두고 카메라만 통과시키거나(밖이 보이게), 창밖에 배경판을 둔다.

### 7.3 엄폐물 높이

| 엄폐물 | 높이 | 웅크려 쏘기 | 서서 쏘기 |
| --- | --- | --- | --- |
| 로우 커버 | 90~110 | 몸이 가려지고 머리만 노출 | 불가 |
| 미드 커버 | 120~140 | 완전 엄폐 | 가슴 위 노출 |
| 하이 커버 | 180~200 | 완전 엄폐 | 어깨로 기대 쏨 |
| 벽 모서리 | 전고 | — | 몸만 숨김 |

로우 커버는 **웅크리기 눈높이(약 100~105)보다 5~10 cm 낮게** 잡는다. 웅크리기 전고를 80으로 두면 90 커버가 "완전 엄폐"가 되어 총이 벽을 통과한다. 엄폐물을 놓을 때는 캡슐로 직접 앉아 보고, 카메라가 엄폐물에 가려 캐릭터를 못 보는지 확인한다.

### 7.4 상호작용 오브젝트의 높이 띠

플레이어가 자연스럽게 상호작용하는 물건은 **눈높이 −40 ~ +20 cm**의 띠에 둔다. 1인칭(눈 160)이면 120~180, 3인칭(눈 152)이면 112~172다.

| 오브젝트 | 높이 | 비고 |
| --- | --- | --- |
| 문 손잡이 | 100~110 | |
| 전등 스위치 | 120~130 | |
| 콘센트 | 30 | |
| 서랍 손잡이 | 70~120 | |
| 선반 물건 | 100~180 | 180 위는 사다리·의자 필요 |
| 바닥 단서(노트·열쇠) | 0~30 | 룩다운 유도가 필요. 하이라이트 필수 |

---

## 8. 실내 카메라 붐(SpringArm) 최적화

실내 탐사에서 "수치 설정"이 실제로 무너지는 곳은 여기다. 복도 180, 문 120을 맞춰도 카메라가 벽에 붙으면 그 방은 못 쓰게 된다.

### 8.1 먼저 기하를 이해한다

```
피벗(눈높이)에서 암이 피치 φ로 L만큼 뻗는다.
  수평 성분 = L·cosφ
  수직 성분 = L·sinφ
복도 축 기준 요 θ로 돌면 카메라의 좌우 이동 = s(숄더 오프셋) + L·cosφ·sinθ
벽까지 쓸 수 있는 좌우 거리 = W/2 − p(probe 반경)
```

따라서 **암을 온전히 유지한 채 돌 수 있는 최대 요**는:

```
sin θ_max = (W/2 − p − s) / (L·cosφ)
```

그리고 **전방위 회전에 필요한 복도 폭**은:

```
W_orbit = 2 × (s + L·cosφ + p)
```

| 암 L | 피치 15°, probe 12, 숄더 0 | 필요 폭 | 180 복도에서 자유 요 |
| --- | --- | --- | --- |
| 180 | 수평 174 | 372 | 26.7° |
| 220 | 수평 213 | 449 | 21.5° |
| 260 | 수평 251 | 526 | 18.1° |
| 300 | 수평 290 | 604 | 15.6° |

읽는 법: **실내에서 3인칭 카메라가 전방위로 도는 것은 사실상 불가능하다.** 4.5~6 m 폭의 홀이 필요하다. 그래서 실내 카메라는 "전방위 회전"이 아니라 **"복도 축을 따라가는 제한된 요 + 암 단축"**으로 설계한다.

### 8.2 파라미터 표

| 파라미터 | 실외 | 실내 | 비고 |
| --- | --- | --- | --- |
| `TargetArmLength` | 300~400 | **180~220** | 문 통과 시 140까지 |
| `TargetOffset` | (0, 0, 40) | (0, 0, 60~80) | 피벗을 가슴 높이로 |
| `SocketOffset` | (0, 30~50, 10) | (0, 25~40, 15) | 어깨 너머. 암 회전에 포함되므로 충돌 검사도 함께 이동 |
| `ProbeSize` | 12 | **12~15** | 12 미만은 벽 모서리를 통과한다 |
| `ProbeChannel` | Camera | Camera | 벽·바닥만 Block, 문틀·난간·소품은 Ignore |
| `bDoCollisionTest` | true | true | |
| `CameraLagSpeed` | 10 | 6~8 | 실내에서 너무 빠르면 어지럽다 |
| `CameraRotationLagSpeed` | 12 | 8~10 | |
| FOV | 90 | 92~98 | 좁은 공간에서 시야 확보. 1인칭 80~90 |
| Near Clip | 10 | 5~8 | 벽에 붙었을 때 뚫림 방지 |
| 최소 암 | — | 120 | 이 아래면 캐릭터가 화면을 덮는다 |
| 1인칭 전환 | — | 90 | 이 아래면 전환 또는 페이드 |

FOV를 96으로 올리면 화면 가장자리 왜곡이 생기지만, 실내에서는 "벽이 가까이 있다"는 정보가 더 중요하다. 1인칭으로 전환하는 게임(예: 폐가 탐사)은 85~90을 유지하고 카메라 회전 속도를 낮춘다.

### 8.3 세 단계 동적 제어

**1단계 — 공간 태그(볼륨) 기반.** 실내 볼륨(`AIndoorVolume`)에 들어가면 목표값을 바꾼다. 방 단위가 아니라 **복도/방/홀** 세 종류로 나눈다.

**2단계 — 충돌 결과 기반 FOV 보정.** SpringArm이 실제로 접힌 길이를 읽어 FOV를 조금 넓힌다. 접힌 상태에서 시야가 좁으면 캐릭터가 화면을 다 먹는다.

**3단계 — 최후 수단.** 암이 120 미만이면 ① 캐릭터를 반투명/디더 페이드하고 ② 그래도 90 미만이면 1인칭으로 전환한다.

```cpp
// IndoorCameraRigComponent.h
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "IndoorCameraRigComponent.generated.h"

class UCameraComponent;
class USpringArmComponent;

UENUM(BlueprintType)
enum class ECameraSpace : uint8
{
    Outdoor,
    Corridor,
    Room,
    Hall
};

UCLASS(ClassGroup = (Camera), meta = (BlueprintSpawnableComponent))
class YOURGAME_API UIndoorCameraRigComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UIndoorCameraRigComponent();

    /** 볼륨이 호출한다. bInstant는 텔레포트·컷신 복귀용. */
    UFUNCTION(BlueprintCallable, Category = "Camera")
    void SetSpace(ECameraSpace NewSpace, bool bInstant = false);

    UFUNCTION(BlueprintPure, Category = "Camera")
    float GetEffectiveArmLength() const;

protected:
    virtual void BeginPlay() override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType,
                               FActorComponentTickFunction* ThisTickFunction) override;

    UPROPERTY() TObjectPtr<USpringArmComponent> Arm;
    UPROPERTY() TObjectPtr<UCameraComponent> Camera;

    UPROPERTY(EditAnywhere, Category = "Camera") float OutdoorArm = 350.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float CorridorArm = 200.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float RoomArm = 230.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float HallArm = 300.f;

    UPROPERTY(EditAnywhere, Category = "Camera") float OutdoorFOV = 90.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float CorridorFOV = 97.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float RoomFOV = 94.f;

    UPROPERTY(EditAnywhere, Category = "Camera") float BlendSpeed = 8.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float SqueezeFOVBoost = 6.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float MinArmBeforeFade = 120.f;
    UPROPERTY(EditAnywhere, Category = "Camera") float FadeStartArm = 160.f;

private:
    ECameraSpace CurrentSpace = ECameraSpace::Outdoor;
    float TargetArm = 350.f;
    float TargetFOV = 90.f;
    bool bInstantBlend = false;

    /** 지난 프레임에 페이드한 프리미티브 (원복용) */
    TArray<TWeakObjectPtr<UPrimitiveComponent>> FadeTargets;
};
```

```cpp
// IndoorCameraRigComponent.cpp
#include "IndoorCameraRigComponent.h"

#include "Camera/CameraComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/Character.h"

UIndoorCameraRigComponent::UIndoorCameraRigComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UIndoorCameraRigComponent::BeginPlay()
{
    Super::BeginPlay();

    if (const ACharacter* Owner = Cast<ACharacter>(GetOwner()))
    {
        Arm = Owner->FindComponentByClass<USpringArmComponent>();
        Camera = Owner->FindComponentByClass<UCameraComponent>();
    }
    SetSpace(ECameraSpace::Outdoor, true);
}

void UIndoorCameraRigComponent::SetSpace(ECameraSpace NewSpace, bool bInstant)
{
    CurrentSpace = NewSpace;
    bInstantBlend = bInstant;

    switch (NewSpace)
    {
    case ECameraSpace::Corridor: TargetArm = CorridorArm; TargetFOV = CorridorFOV; break;
    case ECameraSpace::Room:     TargetArm = RoomArm;     TargetFOV = RoomFOV;     break;
    case ECameraSpace::Hall:     TargetArm = HallArm;     TargetFOV = OutdoorFOV;  break;
    default:                     TargetArm = OutdoorArm;  TargetFOV = OutdoorFOV;  break;
    }
}

float UIndoorCameraRigComponent::GetEffectiveArmLength() const
{
    if (!Arm || !Camera) { return 0.f; }
    // SpringArm이 충돌로 접힌 뒤의 실제 카메라 위치로 길이를 잰다
    return FVector::Dist(Arm->GetComponentLocation(), Camera->GetComponentLocation());
}

void UIndoorCameraRigComponent::TickComponent(float DeltaTime, ELevelTick TickType,
                                              FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (!Arm || !Camera) { return; }

    // 1) 공간 목표값으로 보간 (텔레포트면 즉시)
    Arm->TargetArmLength = bInstantBlend
        ? TargetArm
        : FMath::FInterpTo(Arm->TargetArmLength, TargetArm, DeltaTime, BlendSpeed);

    // 2) 벽에 밀려 실제로 접혔으면 FOV를 조금 넓혀 시야를 보상한다
    const float Effective = GetEffectiveArmLength();
    const float SqueezeRatio = FMath::Clamp(1.f - Effective / FMath::Max(TargetArm, 1.f), 0.f, 1.f);
    const float DesiredFOV = TargetFOV + SqueezeRatio * SqueezeFOVBoost;
    Camera->SetFieldOfView(bInstantBlend
        ? DesiredFOV
        : FMath::FInterpTo(Camera->FieldOfView, DesiredFOV, DeltaTime, BlendSpeed));

    // 3) 너무 가까워지면 캐릭터를 디더 페이드 (머티리얼 파라미터는 8.5절)
    const float Fade = FMath::Clamp((FadeStartArm - Effective) / (FadeStartArm - MinArmBeforeFade), 0.f, 1.f);
    if (const ACharacter* OwnerChar = Cast<ACharacter>(GetOwner()))
    {
        if (USkeletalMeshComponent* Mesh = OwnerChar->GetMesh())
        {
            // 캐릭터 머티리얼이 Custom Primitive Data 0번을 페이드 계수로 읽는다
            Mesh->SetCustomPrimitiveDataFloat(0, Fade);
        }
    }

    bInstantBlend = false;   // 즉시 전환은 한 프레임만
}
```

`bInstantBlend`는 한 프레임만 유지되고 Tick 끝에서 내려간다. 문을 지나며 암이 0.3초에 걸쳐 줄어들면 "카메라가 숨을 들이쉬는" 느낌이 나고, 순간 이동·컷신 복귀에서는 즉시 값으로 바꿔야 화면이 흔들리지 않는다.

### 8.4 볼륨 설계

| 볼륨 | 배치 | 값 |
| --- | --- | --- |
| `AIndoorVolume(Corridor)` | 복도·계단실 | 암 200, FOV 97 |
| `AIndoorVolume(Room)` | 일반 방 | 암 230, FOV 94 |
| `AIndoorVolume(Hall)` | 로비·아트리움 | 암 300, FOV 90 |
| `ADoorTrigger` | 문 앞 120 cm | 암 140, 0.15초 |
| `ACrouchCameraVolume` | 덕트·책상 밑 | 암 120, FOV 100 |

볼륨은 겹칠 수 있다. 겹칠 때는 **가장 안쪽(작은) 볼륨이 이긴다**는 규칙을 두고, 볼륨마다 `Priority`를 준다. 문 트리거는 복도 볼륨보다 우선한다.

### 8.5 벽 페이드와 캐릭터 가리기

카메라와 캐릭터 사이에 벽이 들어오면 두 가지 문제가 동시에 생긴다: ① 캐릭터가 안 보인다 ② 벽이 화면을 채운다.

| 기법 | 원리 | 비용 | 적합 |
| --- | --- | --- | --- |
| 암 단축 | SpringArm이 벽 앞으로 접힘 | 거의 0 | 기본. 항상 켠다 |
| 디더 페이드 | 벽 머티리얼의 `DitherTemporalAA` 마스크 | 낮음(불투명 유지) | 벽·기둥·큰 가구 |
| 캐릭터 실루엣 | 캐릭터를 Custom Depth로 외곽선 | 낮음 | 1인칭 전환 직전 |
| 카메라 측면 이동 | 숄더 스왑 | 0 | 좁은 복도에서 벽에 붙었을 때 |
| 벽 반투명 전환 | 머티리얼을 Translucent로 교체 | 높음(정렬·오버드로우) | 특수 연출만 |

디더 페이드는 **머티리얼 파라미터 하나로** 처리한다. 벽 머티리얼의 최종 Opacity Mask에 `DitherTemporalAA(Opacity)`를 연결하고, `Material Parameter Collection`의 `WallFade`를 0(불투명)~1(투명)로 움직인다. 벽 메시에 `SetCustomPrimitiveDataFloat`로 개별 값을 주면 "카메라를 가리는 벽만" 페이드할 수 있다.

```cpp
// 카메라~캐릭터 사이에 걸린 프리미티브만 페이드 대상으로 표시
void UIndoorCameraRigComponent::UpdateOccluderFade()
{
    constexpr int32 MaxFadeTargets = 8;   // 프레임당 변경 상한

    TArray<FHitResult> Hits;
    FCollisionQueryParams Params(SCENE_QUERY_STAT(CameraOccluder), false, GetOwner());
    GetWorld()->LineTraceMultiByChannel(Hits, Camera->GetComponentLocation(),
                                        GetOwner()->GetActorLocation(), ECC_Visibility, Params);

    // 지난 프레임 대상은 먼저 원복
    for (const TWeakObjectPtr<UPrimitiveComponent>& Old : FadeTargets)
    {
        if (UPrimitiveComponent* Comp = Old.Get())
        {
            Comp->SetCustomPrimitiveDataFloat(0, 0.f);
        }
    }
    FadeTargets.Reset();

    int32 Changed = 0;
    for (const FHitResult& Hit : Hits)
    {
        if (Changed >= MaxFadeTargets) { break; }
        if (UPrimitiveComponent* Comp = Hit.GetComponent())
        {
            Comp->SetCustomPrimitiveDataFloat(0, 1.f);   // 머티리얼에서 WallFade로 읽음
            FadeTargets.Add(Comp);
            ++Changed;
        }
    }
}
```

주의: 매 프레임 모든 벽의 커스텀 데이터를 갱신하면 렌더 상태 변경이 잦아진다. **프레임당 변경 횟수를 8개 이하**로 제한하고, 대상이 바뀔 때만 갱신한다.

### 8.6 1인칭 전환의 경계

| 상황 | 권장 |
| --- | --- |
| 실내 볼륨 진입 | 3인칭 유지, 암 200 |
| 암이 120 미만 | 캐릭터 디더 페이드 |
| 암이 90 미만 | 1인칭 전환(0.2초), 시야 85 |
| 덕트·책상 밑 | 1인칭 강제 |
| 문 통과 | 3인칭 유지, 암 140 + 문틀 Camera Ignore |

전환 시 캐릭터 메시의 머리를 본 단위로 숨기고(`Mesh->HideBoneByName(TEXT("head"), EPhysBodyOp::PBO_None)`), 1인칭 전용 팔·무기 메시만 남긴다. 메시 전체를 `SetOwnerNoSee(true)`로 끄면 그림자까지 사라져 발밑이 비어 보인다. 전환 중 카메라가 캡슐 밖으로 나가면 벽을 뚫으므로, 전환은 반드시 **캡슐 안쪽 지점(눈높이)** 으로 보간한다.

---

## 9. 수치 검증: metrics zoo와 자동 검사

### 9.1 metrics zoo 맵을 만든다

실외에서 검증한 치수는 실내에서 반드시 틀어진다. 프로젝트 초기에 **전용 테스트 맵**을 만들고, 수치가 바뀔 때마다 걸어 본다.

```
/metrics_zoo
  ├─ corridor_120 / 150 / 180 / 240 / 300 / 400   (길이 12 m, 양 끝 문)
  ├─ door_90 / 110 / 120 / 130 / 150 / 200        (벽 두께 15/30 두 종류)
  ├─ ceiling_240 / 270 / 300 / 360 / 450
  ├─ stair_18_28 / 17_29 / 21_21 / 16_32          (층고 320, 계단참 유무)
  ├─ cover_90 / 110 / 140 / 180 / 200             (앉아 쏘기·서서 쏘기)
  ├─ room_3x3 / 4x4 / 6x8 / 8x12                  (가구 밀도 3단계)
  └─ camera_squeeze                                (벽에 붙어 360도 회전)
```

검증 절차는 네 단계다.

1. **걸어 본다.** 12 m 복도를 걷고, 문을 10번 통과하고, 복도 끝에서 180도 돌아본다.
2. **벽에 붙는다.** 벽에 붙은 채 카메라를 벽 쪽으로 돌린다. 화면이 캐릭터로 가득 차면 실패다.
3. **계단을 오른다.** 오르면서 위를 본다. 천장이 화면을 채우면 천장이 낮다.
4. **웅크린다.** 웅크려 문을 통과하고 로우 커버 뒤에 앉는다. 머리가 보이면 커버가 낮다.

### 9.2 계산기로 미리 걸러낸다

[`pipeline/indoor_metric_helper.py`](../pipeline/indoor_metric_helper.py)는 위 1~8장의 계산을 그대로 옮긴 CLI다. 방을 만들기 전에 수치를 넣어 보고, 실패 항목을 먼저 고친다.

```bash
# 용도별 프리셋
python pipeline/indoor_metric_helper.py presets

# 프리셋에서 복도만 200으로 줄였을 때의 종합 판정
python pipeline/indoor_metric_helper.py check --preset office_lab --corridor 200

# 카메라만 따로: 복도 180, 천장 300, 암 220
python pipeline/indoor_metric_helper.py camera --corridor 180 --ceiling 300 --arm 220 --pitch 15

# 계단 21/21은 Blondel은 통과하지만 경사·법규에서 실패한다
python pipeline/indoor_metric_helper.py stairs --riser 21 --tread 21 --floor-height 320
```

출력은 항목별 `OK / WARN / FAIL`과 쾌적도(0~100), 클리핑 위험도(0~100), 판정(권장/양호/주의/위험/탐사 불가)로 나온다. 위험도는 **카메라를 벽 쪽으로 완전히 돌렸을 때**를 기준으로 하므로, 실내에서는 40~70이 정상 범위다. 0을 목표로 하지 않는다.

### 9.3 레벨 스캔 자동화(에디터 파이썬)

방을 200개 만들고 나면 손으로 검사할 수 없다. 방 액터에 태그를 달고 바운드로 폭·높이를 훑는 것만으로도 절반이 걸린다.

```python
# Content/Python/scan_indoor_metrics.py — UE 에디터 파이썬
import unreal

LEVEL_MIN_CEILING = 270.0
DOOR_MIN_WIDTH = 120.0

def scan():
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    issues = []
    for actor in actors:
        if not actor.actor_has_tag("Room"):
            continue
        _, extent = actor.get_actor_bounds(False)
        width = extent.y * 2.0
        height = extent.z * 2.0
        label = actor.get_actor_label()
        if height < LEVEL_MIN_CEILING:
            issues.append(f"{label}: 천장 {height:.0f} cm (< {LEVEL_MIN_CEILING})")
        if width < 300.0:
            issues.append(f"{label}: 방 폭 {width:.0f} cm — 카메라 회전 여유 부족")
        for child in actor.get_attached_actors():
            if child.actor_has_tag("Door"):
                _, door_extent = child.get_actor_bounds(False)
                door_width = door_extent.y * 2.0
                if door_width < DOOR_MIN_WIDTH:
                    issues.append(f"{label}/{child.get_actor_label()}: 문 {door_width:.0f} cm")
    for line in issues or ["문제 없음"]:
        unreal.log(line)

scan()
```

이 스캔은 **바운드 기반 근사**다. 실제 통행 폭은 벽 두께·문틀·가구를 빼야 나오므로, 스캔은 "후보 목록"을 만들고 사람이 걸어 보는 것이 순서다.

---

# Part 2 — 공간 세부 묘사와 환경 스토리텔링

치수가 "지나갈 수 있는가"를 정했다면, 세부 묘사는 "여기서 무슨 일이 있었는가"를 정한다. 이 파트의 원칙은 하나로 요약된다.

> **공간은 상태의 순서로 시간을 말한다.** 물건의 마모·파손·부재·재배치가 같은 시점을 가리키면 플레이어는 이야기를 복원하고, 어긋나면 "게임 맵"으로 읽는다.

---

## 10. 시간의 4층위: 한 방에 역사를 쌓는 법

### 10.1 네 층

| 층 | 무엇을 넣나 | 대표 요소 | 플레이어가 읽는 것 |
| --- | --- | --- | --- |
| 1층 — 건축 골조 | 원래 용도와 구조 | 벽·바닥·창호·문 위치·천장고·마감재 | "여기는 무엇이었나" |
| 2층 — 거주 흔적 | 누가 어떻게 썼나 | 가구 배치, 취향, 직업 도구, 일상 물품, 사진, 달력 | "누가 살았나" |
| 3층 — 사건과 재난 | 무엇이 끊었나 | 파손, 혈흔, 바리케이드, 총탄 자국, 급한 도주, 버려진 신발 | "무슨 일이 있었나" |
| 4층 — 방치와 자연 | 얼마나 지났나 | 먼지 두께, 곰팡이·이끼, 거미줄, 물얼룩, 식물 침투, 산화 | "지금이 언제인가" |

게임에서 이 층위를 **문서·대사로 설명하면 실패**다. 각 층은 조형물로만 존재해야 하고, 플레이어가 방을 한 바퀴 도는 동안 순서대로 읽혀야 한다.

### 10.2 층위별 구현 수단

| 층 | 메시 | 머티리얼/데칼 | 시스템 |
| --- | --- | --- | --- |
| 1층 | 모듈러 킷(벽·바닥·천장), 문틀 | 트림 시트, 벽지/페인트, 타일 | 없음(정적) |
| 2층 | 가구·소품·액자 | 원단·목재·금속, 낙서 데칼 | 문 열림 상태, 서랍 열림, 스위치 |
| 3층 | 파손 변주 메시, 바리케이드, 잔해 | 혈흔·탄흔·그을음 데칼, 긁힘 | 파괴 상태, 아이템 제거, 시체 |
| 4층 | 이끼·덩굴·물웅덩이 | 먼지 마스크, 젖은 자리, 녹, 곰팡이 | 물방울 Niagara, 흔들리는 전등 |

중요한 것은 **같은 물체가 층위를 겹쳐 갖는 것**이다. 책상(1층 위에 놓인 2층)이 뒤집혀 있고(3층) 그 위에 먼지가 쌓여 있으며(4층) 먼지에 손자국이 없다(3층의 시간 = 4층의 시작). 이 네 겹이 한 오브젝트에 있으면 플레이어는 "여기서 싸움이 있었고, 그 뒤로 아무도 오지 않았다"를 스스로 만든다.

### 10.3 시간축 일관성 규칙

가장 흔한 실패는 **층위끼리 시간이 어긋나는 것**이다. 방치된 폐가인데 촛불이 타고 있고, 10년 된 먼지 위에 새 혈흔이 있으며, 곰팡이가 없는 습한 지하실이 그렇다.

```
방의 "사건 시점"을 하나 정한다: D+0 (사건) ~ D+N (현재)
모든 흔적은 D+k 값을 갖는다.
  · 먼지 두께        -> D+N의 함수
  · 곰팡이/이끼      -> 습도 × D+N
  · 혈흔 색          -> D+k (붉음 -> 갈색 -> 검정)
  · 종이의 바램      -> 창가 거리 × D+N
  · 음식 부패        -> D+k (1주~1개월)
  · 식물 침투        -> D+N (몇 달~몇 년)
  · 총탄 자국 주변    -> D+k (가루가 남아 있으면 최근)
```

같은 방에 "최근"과 "오래됨"을 섞으려면 **반드시 두 사건**이 있어야 한다. 예: 10년 전 폐쇄(4층), 3일 전 침입(3층의 새로운 흔적: 최근 발자국, 새 혈흔, 열린 캔). 이때 새 흔적은 **먼지를 밟거나 치운 자국**으로 표현한다. 먼지가 쌓인 곳에 물건이 없으면, 그 물건은 최근에 옮겨진 것이다.

### 10.4 층위를 읽히게 하는 순서

플레이어는 방에 들어와서 다음 순서로 본다: **실루엣 → 큰 물체 → 색 → 작은 물체 → 텍스트**. 따라서:

1. **문에서 보이는 실루엣**에 3층(사건)을 배치한다. 넘어진 의자, 기울어진 선반.
2. **방 중앙**에 2층(누가 살았나)을 배치한다. 식탁, 작업대.
3. **벽과 바닥**에 4층(시간)을 깐다. 얼룩, 먼지, 이끼.
4. **가까이 가야 보이는 곳**에 3층의 디테일(혈흔, 총탄, 편지)을 둔다.

---

## 11. 단서 설계: 3단서 + 1질문

### 11.1 텍스트를 다 지워도 읽히는가

환경 스토리텔링의 유일한 합격 기준은 이것이다.

> 방의 노트·오디오 로그·대사를 전부 지우고 처음 보는 사람을 통과시킨 뒤, "여기서 무슨 일이 있었나?"라고 물었을 때 **대부분이 같은 답**을 하면 성공이다. "무엇이 있었는지"가 아니라 "어떻게 생겼는지"를 말하면 그것은 장식이지 이야기가 아니다.

이 테스트는 [GameDesign.gg의 환경 스토리텔링 가이드](https://gamedesign.gg/articles/environmental-storytelling-in-level-design/)가 제시한 기준이고, 학술 쪽에서도 같은 결론에 도달한다. SMU Guildhall의 논문은 플레이어가 의도한 서사의 **약 80%**를 이해하면 성공으로 본다([He, 2024](https://scholar.smu.edu/cgi/viewcontent.cgi?article=1009&context=guildhall_leveldesign_etds)). 100%를 노리면 과잉 설명이 된다.

### 11.2 세 개의 단서와 하나의 질문

| 요소 | 역할 | 예 |
| --- | --- | --- |
| 앵커 단서 | 자연 동선에서 반드시 보인다 | 문을 막은 책장, 뒤집힌 식탁 |
| 보강 단서 1 | 같은 결론을 다른 재료로 | 바닥의 끌린 자국 |
| 보강 단서 2 | 같은 결론을 다른 시간으로 | 마르지 않은 핏방울 |
| 작은 질문 1 | 결론을 100%로 닫지 않는다 | "왜 문은 안쪽에서 막혔나?" |

세 개 미만이면 플레이어는 해석을 확정하지 않고 지나가고, 네 개를 모두 설명하면 호기심이 남지 않는다. 이 "3+1" 규칙은 위 가이드의 권고이며, 실무에서도 방마다 단서를 3개로 제한하면 제작비가 통제된다.

### 11.3 단서의 어휘

단서는 감정이 아니라 **물리적 사실**이어야 한다.

| 어휘 | 예 | 읽히는 것 |
| --- | --- | --- |
| 파손 | 부서진 유리, 구부러진 문손잡이 | 폭력의 방향 |
| 이동 | 벽 쪽으로 밀린 가구, 문 앞의 매트 | 도주 경로 |
| 소모 | 빈 물병 더미, 타다 남은 양초 | 체류 시간 |
| 부재 | 액자만 남은 자국, 서랍은 열리고 물건은 없음 | 누군가 먼저 왔다 |
| 반복 | 같은 표시가 여러 문에 | 규칙·경고 |
| 온도/습기 | 결로, 곰팡이, 재 없는 난로 | 시간과 계절 |
| 위생 | 쌓인 그릇, 변기에 쌓인 것 | 정신 상태·포기 |

### 11.4 before / after 두 프레임

가장 신뢰할 수 있는 구성은 **"정상 상태"와 "교란된 상태"를 한 화면에** 놓는 것이다.

- 깔끔한 사무실 + 한 책상만 쓸어낸 흔적 → 급히 떠났다
- 생일상 + 손대지 않은 케이크 + 모든 의자가 뒤로 밀림 → 식사가 중단됐다
- 규칙적으로 쌓인 상자 + 한쪽만 무너진 더미 → 누군가 뒤졌다

두 상태가 같은 재료로 만들어져야 한다(같은 의자, 같은 식기). 다른 세트의 소품을 섞으면 "연출"로 보인다.

---

## 12. 밀도와 리듬: 방마다 이야기 하나

### 12.1 방 하나에 이야기 하나

방마다 앵커 단서 하나, 보강 둘, 질문 하나. 이걸 넘기면 플레이어는 어느 것도 기억하지 못한다. 방이 길면 **구역(zone)** 으로 나눈다: 입구 구역(첫인상), 중심 구역(주요 단서), 구석 구역(보상·세부).

### 12.2 대비가 밀도를 만든다

모든 방이 밀집하면 어디도 밀집해 보이지 않는다. 리듬은 **빈 방 → 보통 → 밀집**의 3단으로 만든다.

| 방 등급 | 역할 | 소품 밀도 | 예산(40 m² 기준) |
| --- | --- | --- | --- |
| A — 핵심 서사 | 이야기의 무대 | cluttered (1.25/m²) | 50개 내외, 종류 20~30 |
| B — 통과·탐색 | 이동과 호흡 | normal (0.45/m²) | 18개 내외, 종류 10~14 |
| C — 배경·복도 | 시선의 쉼 | sparse (0.20/m²) | 8개 내외, 종류 4~6 |

A 방 앞에는 반드시 C 방이나 빈 복도를 둔다. 어두운 복도를 지나 문을 열면 A 방이 밝게 터지는 구성이 가장 값싸고 강력하다.

### 12.3 한 화면의 오브젝트 수

인간은 한 번에 5~9개의 오브젝트를 구분한다. 방에 들어섰을 때 **시선이 머무는 오브젝트를 7개 이하**로 유지하고, 나머지는 그룹(더미·선반·상자)으로 뭉친다.

- 바닥에 흩어진 소품은 3~5개씩 무리로. 하나씩 흩으면 시각적 소음이 된다.
- 같은 무리 안에서는 **같은 재질 계열**을 쓴다(종이·천·금속).
- 벽은 비워 둔다. 벽에 걸린 것이 5개를 넘으면 방의 중심이 사라진다.

### 12.4 밀도와 통행

소품은 통행 폭을 먹는다. 복도 180에 양옆으로 40 cm짜리 상자를 놓으면 실효 폭이 100이 되어 캡슐(68)이 겨우 지나간다. 소품을 놓을 때는 `check`의 `corridor.props` 값을 다시 계산한다.

```bash
python pipeline/indoor_metric_helper.py check --preset dungeon_bunker --corridor 180
# corridor.props: 양옆 각 30 cm -> WARN
```

---

## 13. 시각적 길찾기와 프레이밍

### 13.1 네 가지 빵부스러기

| 수단 | 구현 | 강도 |
| --- | --- | --- |
| 빛 | 가로등·비상구·창으로 들어오는 빛줄기, 손전등이 닿는 벽 | 강함. 가장 먼저 읽힌다 |
| 색 | 노란 페인트(상호작용), 붉은 천(위험), 녹색 비상구 | 중간. 규칙을 3회 이상 반복해야 학습된다 |
| 형태 | 문틀·아치·계단의 반복, 시선이 통하는 구멍 | 중간. 공간 자체가 화살표가 된다 |
| 흔적 | 핏자국, 끌린 자국, 물웅덩이, 발자국 | 약함. 가까이 가야 읽힌다 |

**빛의 줄**이 실내에서 가장 강하다. 복도 끝의 창에서 들어오는 빛, 비상구의 녹색, 아래층에서 새어 오는 빛. 광원을 "밝히는 도구"가 아니라 **"다음 공간을 가리키는 화살표"**로 배치한다.

### 13.2 프레이밍: 다음 공간을 미리 보여준다

실내 탐사의 만족은 "보이는 곳에 갈 수 있다"에서 온다.

- 문 너머, 난간 너머, 깨진 벽 틈으로 **다음 목표 공간의 일부**를 먼저 보여준다.
- 그 공간은 지금 갈 수 없어야 한다(잠긴 문, 무너진 계단). 나중에 그 문을 열었을 때 "아까 그 방"이라는 기억이 보상이 된다.
- 창문은 가장 값싼 프레이밍 도구다. 창밖으로 다른 건물의 불빛을 보여주면 세계가 넓어진다.

### 13.3 유도의 규칙

1. **한 번에 하나만.** 빛·색·형태가 동시에 다른 방향을 가리키면 플레이어는 멈춘다.
2. **주 동선은 밝게, 보상은 어둡게.** 보상(아이템·단서)은 플레이어가 스스로 발견해야 기억에 남는다.
3. **가짜 유도는 한 번만.** 벽에 그린 화살표, 일부러 틀린 표지판은 한 번은 재미있고 두 번은 배신이다.
4. **돌아오는 길을 표시한다.** 편도 동선이면 문 손잡이 위치·벽 색·조명 색으로 방향을 남긴다.

### 13.4 색의 의미 규칙

| 색 | 의미 | 반복 횟수 |
| --- | --- | --- |
| 노랑 | 상호작용·주의 | 레벨당 10회 이상 |
| 빨강 | 위험·차단·비상 | 5회 이상 |
| 초록 | 출구·안전 | 3회 이상 |
| 파랑 | 냉각·물·전기 | 3회 이상 |
| 흰색 | 중립·안내 | 제한 없음 |

색은 **재질에도** 적용해야 한다. 노란 페인트를 칠한 배관, 노란 손잡이, 노란 바닥선이 같은 의미로 반복되면 플레이어는 색만 보고 상호작용을 예측한다.

---

## 14. 실내 조명 연출

### 14.1 조명의 세 층

| 층 | 역할 | 광원 | 비율 |
| --- | --- | --- | --- |
| 주광(Key) | 방의 성격과 방향 | 창으로 들어오는 태양, 큰 형광등 | 60~70% |
| 생활광(Fill) | 어둠을 걷고 형태를 읽힌다 | 스탠드, 모니터, 비상등 | 20~30% |
| 강조광(Accent) | 단서·목표를 가리킨다 | 손전등, 촛불, 틈새 빛 | 5~15% |

실내는 이 세 층의 **비율**로 무드를 만든다. 낮의 폐가(주광 70), 밤의 연구소(생활광 60 + 비상등), 지하(강조광 80)가 같은 방이라도 전혀 다르게 보인다.

### 14.2 노출과 대비

실내 탐사에서 자동 노출은 적이다. 손전등을 켜면 화면 전체가 어두워지고, 창가에 서면 실내가 까맣게 죽는다. **고정 노출**로 두고 방마다 값을 정한다.

| 무드 | EV100 | 대비(Key:Fill) | 비고 |
| --- | --- | --- | --- |
| 낮 실내(창밝음) | 11~13 | 1:8~1:16 | 창밖은 2~3 스톱 오버 |
| 흐린 낮·저녁 | 9~11 | 1:16~1:32 | |
| 밤 실내(등 켜짐) | 7~9 | 1:8 | |
| 밤 실내(등 꺼짐) | 4~6 | 1:64 이상 | 손전등 없으면 안 보인다 |
| 지하·벙커 | 3~5 | 1:100 | 비상등만 |

엔진 설정은 Post Process Volume의 `Metering Mode`를 `Manual`로 두고(또는 `r.DefaultFeature.AutoExposure=False`), `Exposure Compensation`(EV100)으로 방마다 조정한다. 자동 노출을 꼭 쓰려면 `Speed Up/Down`을 0.8 이상으로 느리게 해서 손전등 토글에 반응하지 않게 한다.

### 14.3 광원 예산

| 항목 | 권장 | 이유 |
| --- | --- | --- |
| 방당 동적 광원 | 3~5 (그림자 2 이하) | VSM 페이지·그림자 비용 |
| 방당 감쇠 거리 | 벽 두께 + 300 cm | 벽을 넘어 다음 방을 밝히지 않게 |
| 실내 IES 프로파일 | 형광등·백열등 IES 사용 | 실제 배광이 형태를 만든다 |
| 반투명 그림자 | 원칙적으로 끔 | 비용 폭증 |
| 라이트 함수 | 정적 방은 Stationary/Movable 혼합 | Lumen은 Movable 위주 |

VSM(Virtual Shadow Map)은 방 하나에 점광원을 20개 넣으면 페이지가 부족해 그림자가 사라지거나 새어 들어온다. **방당 동적 그림자 광원을 2개 이하**로 두고, 나머지는 이미시브·데칼·라이트 함수 없이 처리한다.

### 14.4 손전등 설계

손전등은 실내 탐사의 **주 인터랙션**이자 조명이다. 수치보다 중요한 것은 "무엇이 안 보이는가"다.

| 파라미터 | 값 | 이유 |
| --- | --- | --- |
| Inner Cone | 12~18° | 중심이 밝아야 초점이 생긴다 |
| Outer Cone | 35~45° | 주변부는 부드럽게 |
| Attenuation Radius | 1200~2000 cm | 방 하나를 겨우 비추는 거리 |
| Intensity | 8~20 (cd) | 주변 조명보다 2~3 스톱 위 |
| Temperature | 4000~5000K | 차갑고 불편한 느낌 |
| 흔들림 | 카메라 회전 지연 0.1~0.15초 | 손전등이 손에 들려 있다는 감각 |
| 그림자 | Cast Shadows ON | 물체가 그림자를 만들어야 공간이 읽힌다 |

연출 규칙:
- 손전등이 **닿지 않는 곳**을 항상 남긴다. 전부 밝히면 공간이 사라진다.
- 배터리·깜빡임은 긴장을 만들지만, **어두워서 못 지나가는 구간**을 만들면 안 된다(플레이어가 막힌다). 깜빡임은 연출 구간에서만.
- 손전등을 켜면 몬스터가 반응하는 규칙은 "켜면 위험, 끄면 안 보임"의 트레이드오프를 만든다.

### 14.5 볼류메트릭과 먼지

| 요소 | 설정 | 효과 |
| --- | --- | --- |
| Volumetric Fog | 방 단위 볼륨, 밀도 0.02~0.08 | 빛줄기가 보인다 |
| 먼지 입자(Niagara) | 카메라 주변 0.5~2 m, 50~200개 | 공기감. 과하면 눈이 아프다 |
| 빛줄기 | 창·틈새에서 Spot Light + Fog | 가장 강력한 실내 연출 |
| 바닥 먼지 | 데칼·버텍스 블렌드 | 발자국·끌린 자국과 함께 |

볼류메트릭은 비용이 크다. 방 안에서만 켜고(`Volumetric Fog`가 붙은 Exponential Height Fog Volume), 복도에서는 밀도를 낮춘다. 먼지 입자는 카메라 근처에서만 스폰해 화면 밖 낭비를 줄인다.

### 14.6 Lumen에서 실내가 깨지는 지점

| 증상 | 원인 | 대응 |
| --- | --- | --- |
| 벽 너머 빛이 샌다 | 거리 필드 복셀보다 얇은 벽 | 벽 두께 15 cm 이상, 양면 메시 금지 |
| 문틈으로 빛이 번진다 | 서피스 캐시 카드가 개구부를 덮음 | 문틀을 별도 메시로, 개구부 주변 카드 확인 |
| 방이 회색으로 뜬다 | 서피스 캐시 미커버(분홍) | 메시 단순화, `Lumen Card` 수 조정 |
| 그림자가 사라진다 | VSM 페이지 부족 | 그림자 광원 수 제한, 그림자 거리 축소 |
| 손전등이 안 보인다 | 스크린 트레이스 실패 | 손전등을 카메라 앞 50 cm에 두고 반경 확보 |

Lumen은 **얇은 메시를 표현하지 못한다.** 소프트웨어 레이트레이싱은 메시 거리 필드를 복셀화하고, 복셀보다 얇은 벽은 구멍으로 표현되어 간접광이 통과한다([Lumen SIGGRAPH 2022](https://advances.realtimerendering.com/s2022/SIGGRAPH2022-Advances-Lumen-Wright%20et%20al.pdf)). 두께 규칙과 카드 커버리지 확인은 [오픈월드 콘텐츠 가이드 3.3절](open_world_content_and_architecture_guide.md)에 정리되어 있다.

---

## 15. 촉각·청각 디테일

### 15.1 표면 재질이 소리를 만든다

발소리·충돌음·상호작용음은 **Physical Material**로 결정한다. 메시마다 `Phys Material Override`를 지정하고, `EPhysicalSurface` 열거형으로 게임플레이 로직과 연결한다.

| Surface Type | 재질 | 발소리 | 부가 효과 |
| --- | --- | --- | --- |
| Wood | 마루·데크 | 삐걱·둔탁 | 파편 |
| Carpet | 카펫·러그 | 무음에 가까움 | 먼지 |
| Tile | 타일·욕실 | 짧고 딱딱 | 물방울 |
| Concrete | 콘크리트·지하 | 넓은 반향 | 먼지 |
| Metal | 철판·계단 | 금속 울림 | 스파크 |
| Glass | 유리·병 | 깨짐·짧은 충격 | 파편·피 |
| Water | 물웅덩이 | 첨벙 | 물보라 |
| Gravel | 자갈·잔해 | 바스락 | 먼지 |
| Flesh | 시체·점액 | 둔탁 | — |

발소리는 **애님 노티파이 + 라인 트레이스**로 처리한다. 매 프레임 트레이스하지 않고, 발이 땅에 닿는 프레임에만 한다.

```cpp
// UFootstepComponent::PlayFootstep
void UFootstepComponent::PlayFootstep(USkeletalMeshComponent* Mesh, FName SocketName)
{
    if (!Mesh || !FootstepTable) { return; }

    const FVector Foot = Mesh->GetSocketLocation(SocketName);
    const FVector Start = Foot + FVector(0, 0, 30.f);
    const FVector End = Foot - FVector(0, 0, 60.f);

    FCollisionQueryParams Params(SCENE_QUERY_STAT(Footstep), false, GetOwner());
    Params.bReturnPhysicalMaterial = true;

    FHitResult Hit;
    if (!GetWorld()->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility, Params)) { return; }

    const EPhysicalSurface Surface = UGameplayStatics::GetSurfaceType(Hit);
    // 프로젝트 설정의 Physical Surface 이름이 행 이름이 된다 (예: "Wood", "Carpet")
    const FName RowName(*StaticEnum<EPhysicalSurface>()->GetNameStringByValue((int64)Surface));
    if (const FFootstepRow* Row = FootstepTable->FindRow<FFootstepRow>(RowName, TEXT("Footstep")))
    {
        // 달리기·웅크리기·젖은 상태에 따라 볼륨·피치를 바꾼다
        const float SpeedScale = FMath::GetMappedRangeValueClamped(
            FVector2D(0.f, 600.f), FVector2D(0.6f, 1.2f), GetOwner()->GetVelocity().Size());
        UGameplayStatics::PlaySoundAtLocation(this, Row->Sound, Hit.ImpactPoint,
                                              Row->Volume * SpeedScale, Row->Pitch);
        if (Row->Niagara)
        {
            UNiagaraFunctionLibrary::SpawnSystemAtLocation(
                this, Row->Niagara, Hit.ImpactPoint, Hit.ImpactNormal.Rotation());
        }
    }
}
```

`bReturnPhysicalMaterial = true`를 빠뜨리면 모든 발소리가 같은 소리가 된다. 그리고 **데칼 위를 걸을 때**도 바닥 재질을 따라가야 한다(데칼은 콜리전이 없으므로 바닥 메시의 Physical Material이 답이다).

### 15.2 공간이 소리를 만든다

| 요소 | 구현 | 효과 |
| --- | --- | --- |
| 리버브 존 | `Audio Volume` + Reverb Effect (복도/방/지하) | 공간의 크기감 |
| 차폐(Occlusion) | 사운드에 `Occlusion` 활성, 벽 두께 반영 | 문 너머 소리가 먹먹해진다 |
| 감쇠 | 3D Attenuation, 실내 800~1500 cm | 다음 방 소리가 새지 않게 |
| 환경음 | 물방울·삐걱·바람 (랜덤 간격 4~15초) | 정적을 채운다 |
| 반응음 | 발소리·문·유리·금속 | 플레이어 행동의 확인 |

실내에서 가장 효과적인 소리는 **"방금 무언가 멈춘 소리"**다. 물방울이 떨어지다가 멈추고, 환풍기가 멈추고, 음악이 끊긴다. 소리의 **부재**가 소리보다 무섭다.

### 15.3 물리 인터랙션

| 오브젝트 | 구현 | 비용 | 비고 |
| --- | --- | --- | --- |
| 여닫이 문 | 물리 제약(경첩) 또는 애니메이션 + 소리 | 낮음 | 애니메이션이 안정적. 물리는 잼 발생 |
| 서랍 | 애니메이션 + `Timeline` | 낮음 | 내용물은 별도 메시 |
| 매달린 전등 | `PhysicsConstraint` + Light | 중간 | 바람·충격에 흔들린다 |
| 잔해 | Geometry Collection(Chaos) 또는 개별 강체 | 높음 | 파괴 가능 구간만 |
| 병·캔 | 강체 + 사운드 + 파편 | 중간 | 개수가 많으면 수면 처리 |
| 스위치 | 상호작용 → 라이트 토글 + 소리 + 먼지 | 낮음 | 가장 값싼 "살아있는 공간" |

물리 오브젝트는 **플레이어가 건드릴 수 있는 것만** 물리로 만든다. 배경 소품에 리지드 바디를 넣으면 예산이 무너진다. `Simulate Physics`는 상호작용 태그가 붙은 것만, 나머지는 스태틱.

---

## 16. 서사 오브젝트의 기술 구현

### 16.1 데칼

| 용도 | 방식 | 주의 |
| --- | --- | --- |
| 혈흔·탄흔·낙서 | DBuffer Decal (Deferred) | 반투명 메시보다 싸다 |
| 바닥 먼지·젖은 자리 | 데칼 또는 버텍스 블렌드 | 겹치면 z-fighting. 각도 1~2도 |
| 벽 얼룩 | 데칼 + 높이 오프셋 | 벽 두께보다 얇게 |
| 반복 데칼 | Decal Actor 풀 | 방마다 5~10개 이하 |

데칼은 **텍셀 밀도**가 품질을 결정한다. 1 m 크기 데칼에 1024 텍스처를 쓰면 1 texel/mm 수준으로 선명하고, 4 m에 쓰면 뭉개진다. 데칼 크기에 맞춰 텍스처를 고른다.

### 16.2 버텍스 블렌드와 파라미터

먼지는 메시를 교체하지 않고 **머티리얼 파라미터**로 표현한다.

- 벽·바닥 메시에 `Vertex Color R = 먼지`, `G = 젖음`, `B = 이끼` 마스크를 칠한다.
- 머티리얼은 이 마스크로 텍스처를 블렌드한다.
- 방 단위로 진행도를 바꾸려면 `Material Parameter Collection`에 `RoomDust` 하나를 두고 방 볼륨이 값을 바꾼다.

이 방식은 메시 변주(먼지 낀 버전, 젖은 버전)를 만들지 않아도 되고, 메모리·머티리얼 수가 늘지 않는다. 대신 **버텍스 컬러를 칠하는 작업**이 필요하다(블렌더에서 정점 페인트).

### 16.3 파괴와 변주

| 방식 | 사용 | 비용 |
| --- | --- | --- |
| 메시 변주(온전/파손/부서짐) | 가구·문·유리 | 메모리 ×3, 가장 안정적 |
| 본 분리(스켈레톤) | 의자 다리, 선반 | 애니메이션 비용 |
| Chaos 파괴 | 벽·바닥 일부 | 높음. 연출 구간만 |
| 필드 + 강체 잔해 | 작은 파편 | 중간. 수면 필수 |

파손 메시를 만들 때는 **파편이 남는 방향**을 정한다. 안쪽으로 부서진 문은 "밖에서 밀었다", 바깥으로 부서진 문은 "안에서 뚫고 나왔다"를 말한다.

### 16.4 텍스트(리더블) 배치

- 플레이어가 **서는 자리**에 둔다(문 앞 1.5 m, 책상 앞 80 cm).
- 조명을 준다. 어두운 구석의 노트는 아무도 안 읽는다.
- 한 장에 3~5문장. 그 이상은 오디오 로그로.
- 텍스트는 **단서의 보강**이지 대체가 아니다. 텍스트를 지워도 방이 읽혀야 한다(11.1절).

### 16.5 방 하나를 채우는 8단계

```
① 층위 결정      방의 사건 시점(D+k)과 네 층위의 강도를 정한다
② 동선 표시      문에서 출구까지의 시선을 그리고, 앵커 단서 위치를 정한다
③ 대형 가구      실제 치수로 배치. 통행 폭을 계산기로 확인한다
④ 2층 흔적       누가 살았는지: 취향·직업·일상 물품 3~5개
⑤ 3층 사건       파손·이동·부재를 3개. 방향과 시간이 일치하게
⑥ 4층 방치       먼지·이끼·물얼룩을 버텍스/데칼로. 과하지 않게
⑦ 조명           주광·생활광·강조광 비율을 정하고, 그림자 광원 2개 이하
⑧ 소리·검증      리버브·환경음, 그 다음 텍스트를 모두 끄고 걸어 본다
```

---

## 17. 자주 하는 실패

| 실패 | 증상 | 원인 | 처방 |
| --- | --- | --- | --- |
| 시간축 불일치 | "폐가인데 최근 흔적" | 층위별로 다른 날에 만들었다 | 방마다 D+k 값을 표에 적고 모든 흔적을 검수 |
| 과밀 | 방이 창고처럼 보인다 | 소품을 채우면 좋다고 생각 | A/B/C 등급과 7개 규칙(12장) |
| 텍스트 의존 | 노트를 안 읽으면 이해 불가 | 이야기를 문서로 설계 | 텍스트 제거 테스트 |
| 조명 과잉 | 모든 것이 보여 긴장이 없다 | 손전등+비상등+창+램프 전부 켬 | 광원 3~5개, 강조광 1개 |
| 프리팹 티 | 방마다 같은 배치 | 같은 소품을 같은 각도로 | 회전·스케일·색·주변 소품 교체 |
| 문 뒤 공간 없음 | 문을 열면 벽 | 평면을 벽 위에 그렸다 | 문 앞 1 m 확보 |
| 복도가 미로 | 같은 복도가 반복 | 방향 단서 없음 | 구간마다 색·빛·재질 변화 |
| 소리 없음 | 걸어도 공간이 안 느껴진다 | 발소리 미구현 | Physical Material + 노티파이 |
| 카메라 뚫림 | 벽 너머가 보인다 | 벽 두께·probe·채널 | 8장, 벽 15 cm, probe 12 |
| 밝기 고정 안 됨 | 손전등 켤 때 화면 깜빡 | 자동 노출 | 고정 노출 + EV100 |

---

# Part 3 — 레이아웃 토폴로지와 최적화

실내는 "폴리곤이 적은 대신 광원이 많은" 환경이다. 그래서 예산은 삼각형이 아니라 **방 수·광원 수·시야 길이**로 잡는다. 이 파트는 방을 어떻게 배치하고, 무엇을 언제 켜고 끄는가를 다룬다.

---

## 18. 방 배치 토폴로지

### 18.1 여섯 가지 기본형

| 토폴로지 | 구조 | 장점 | 위험 | 적합 |
| --- | --- | --- | --- | --- |
| 선형(Corridor) | 복도 하나에 방이 붙는다 | 동선이 명확, 제작 쉬움 | 지루함, 되돌아가기 길다 | 호러·연출 중심 |
| 허브 앤 스포크 | 중앙 홀 + 방 여러 개 | 방향 선택, 공간 위계 | 허브가 병목·카메라 부담 | 연구소·병원 |
| 루프(Loop) | 방들이 고리로 연결 | 막다른 길 없음, 지름길 | 길을 잃음 | 탐사·액션 |
| 격자(Grid) | 방이 규칙적으로 배열 | 확장 쉬움, 오피스 느낌 | 개성 없음, 시야 반복 | 오피스·아파트 |
| 초크포인트(Choke) | 좁은 목 + 넓은 방 | 긴장·방어 지점 | 카메라 문제 집중 | 던전·벙커 |
| 중첩 루프 | 루프 안의 루프 | 깊이감, 메트로이드바니아 | 제작·검증 비용 | 대형 던전 |

### 18.2 루프를 최소 하나 넣는다

선형 복도만 이어 붙이면 플레이어는 "왔던 길을 되돌아가는" 시간을 보낸다. 탐사에서는 이 시간이 곧 지루함이다.

```
나쁨:  A → B → C → D → (끝) → D → C → B → A
좋음:  A → B → C → D → (지름길) → B
```

- 루프는 **한 구역에 하나**면 충분하다. 3개를 넘으면 길을 잃는다.
- 지름길은 **처음에 잠겨 있고**, 반대편에서 열린다(문·엘리베이터·무너진 벽). 플레이어가 "아까 그 문"을 기억하게 만든다.
- 루프의 양쪽 끝은 **다른 성격**이어야 한다(밝은 복도 ↔ 어두운 계단). 같은 복도가 이어지면 루프인지 착각한다.

### 18.3 막다른 길은 보상으로 정당화한다

막다른 길이 나쁜 이유는 "돌아오는 시간"이지 "끝" 자체가 아니다. 막다른 방에 다음 중 하나를 두면 동선이 된다.

- 아이템·열쇠·단서
- 지름길(반대편에서만 열리는 문)
- 시점(창밖의 경치, 아래층을 내려다보는 구멍)
- 서사적 보상(가장 강한 장면)

보상이 없으면 그 방은 지운다. "분위기용 방"은 한 구역에 하나까지.

### 18.4 방 크기 모듈

| 모듈 | 면적 | 용도 | 소품 등급 |
| --- | --- | --- | --- |
| 3 x 3 m | 9 m² | 화장실·창고·옷장 | C |
| 4 x 4 m | 16 m² | 침실·사무실 | B |
| 4 x 6 m | 24 m² | 거실·회의실 | B |
| 6 x 8 m | 48 m² | 식당·실험실 | A |
| 8 x 12 m | 96 m² | 홀·창고 | A(대형 소품) |

모듈은 100/200/400 cm 그리드에 맞춘다. 4 x 4 m 방을 400 x 400으로 만들면 벽 두께 15를 안쪽으로 넣어 실내 유효 370 x 370이 된다. **실내 유효 치수**로 통행·가구를 계산해야 한다.

### 18.5 층·동선 위계

| 층 | 역할 | 시야 |
| --- | --- | --- |
| 지상 1층 | 진입·안내 | 밝고 열린 시야 |
| 지상 2층+ | 거주·사무 | 복도 + 방 |
| 지하 1층 | 시설·창고 | 인공 조명, 낮은 천장 |
| 지하 2층+ | 비밀·코어 | 손전등, 초크포인트 |

층이 내려갈수록 천장이 낮아지고(400 → 320 → 280), 광원이 줄고, 복도가 좁아지는 규칙을 쓰면 플레이어는 **층을 내려간다는 것 자체**를 몸으로 느낀다. 단, 3인칭이면 280 아래로 내리지 않는다(5.4절).

---

## 19. 락앤키 그래프와 동선

### 19.1 열쇠의 종류

| 열쇠 | 예 | 특징 |
| --- | --- | --- |
| 물리 열쇠 | 카드키, 열쇠, 차키 | 인벤토리 필요. 가장 명확 |
| 코드/정보 | 비밀번호, 도면, 편지 | 읽어야 한다. 텍스트 의존 위험 |
| 도구 | 볼트커터, 삽, 소화기 | 능력 습득. 되돌아가기 유도 |
| 능력 | 웅크리기, 점프 강화, 해킹 | 메트로이드바니아 |
| 환경 | 전원 켜기, 물 빼기 | 공간 자체가 열쇠 |

### 19.2 그래프 규칙

```
1. 자물쇠보다 열쇠를 먼저 보여준다 (또는 자물쇠를 먼저 보여주고 열쇠를 찾게 한다)
2. 한 구역의 자물쇠는 3개 이하
3. 열쇠를 얻은 직후 첫 자물쇠가 보이게 한다 (습득의 보상)
4. 순서를 건너뛸 수 있는 지름길은 하나까지 허용
5. 열쇠 없이 열리는 문이 전체의 60% 이상 (선택의 여지)
```

### 19.3 구역 길이

| 구역 | 목표 시간 | 방 수 | 자물쇠 |
| --- | --- | --- | --- |
| 소구역 | 5~10분 | 4~8 | 1 |
| 중구역 | 15~25분 | 10~20 | 2~3 |
| 대구역(챕터) | 40~60분 | 30~50 | 4~6 |

탐사 게임에서 20분 이상 자물쇠가 없는 구간은 "목적 없는 산책"이 된다. 반대로 5분마다 자물쇠가 나오면 체크리스트가 된다.

---

## 20. 소품 밀도 예산

### 20.1 등급표

| 등급 | 개체(/m²) | 종류(25 m²당) | 평균 삼각형 | 쓰는 곳 |
| --- | --- | --- | --- | --- |
| sparse | 0.20 | 4 | 12,000 | 복도·배경 방 |
| normal | 0.45 | 7 | 18,000 | 일반 방 |
| dense | 0.80 | 10 | 25,000 | 핵심 방 |
| cluttered | 1.25 | 14 | 35,000 | 사건 현장·폐가 |

```bash
$ python pipeline/indoor_metric_helper.py clutter --area 40 --grade dense
40 m^2 · dense · Nanite
  소품 개체        32개
  소품 종류        16종 (종류당 2.0개)
  컴포넌트         ISM
  삼각형 추정      800,000 (평균 25,000)
  드로우 추정      24 (종류 x 머티리얼)
```

### 20.2 인스턴싱: Nanite 프로젝트에서는 ISM이 기본

| 대상 | 컴포넌트 | 이유 |
| --- | --- | --- |
| Nanite 소품(정적) | **ISM** | Nanite가 클러스터 단위 컬링·LOD를 하므로 HISM의 트리는 중복 비용 |
| 비-Nanite 소품 | **HISM** | 클러스터 단위 컬링·LOD가 필요 |
| 상호작용 소품 | 개별 액터 또는 ISM + 교체 | 인스턴스는 개별 콜리전이 없다 |
| 파괴 가능 소품 | 개별 액터(또는 GC) | 상태 추적 |
| 식생·잔해 대량 | PCG + ISM | [오픈월드 제작 파이프라인](open_world_creation_pipeline.md) 4장 |

Epic 개발자 답변(2025-09)은 "HISM은 비-Nanite 플랫폼을 타깃할 때만 쓰고, Nanite 프로젝트에서는 ISM으로 충분하다"고 정리한다. Nanite 메시는 전통적 LOD가 없어 HISM의 LOD 선택 이점도 사라진다.

### 20.3 텍스처가 진짜 예산이다

소품 1종은 보통 텍스처 3장(BaseColor·Normal·ORM)을 쓴다. 2K BC7 기준 한 장이 약 5.5 MB(밉 포함), 세 장이면 16 MB다.

```
소품 40종 × 16 MB = 640 MB  (텍스처 풀 전체를 먹는다)
아틀라스/트림 시트로 4종씩 묶으면 160 MB
```

그래서 실내 소품은 **트림 시트 2048 한 장 + 머티리얼 1~2개**로 묶는 것이 정석이다([오픈월드 콘텐츠 가이드 3.6절](open_world_content_and_architecture_guide.md)). 스케일·회전·색 변주로 다양성을 만드는 편이 싸다.

### 20.4 밀도와 성능의 균형

| 지표 | 위험 신호 | 대응 |
| --- | --- | --- |
| 방 하나 소품 종류 > 25 | 프리팹 티, 텍스처 메모리 | 아틀라스 통합, 변주 |
| 방 하나 소품 개체 > 80 | 통행·시야 방해 | 그룹화, 절반 삭제 |
| 방 하나 삼각형 > 1.2M | 화면에 두 방이 보이면 초과 | Nanite fallback, LOD, 컬링 |
| 같은 메시 1~2회 반복 | 어색한 복제 | 최소 3회 또는 1회만 |

---

## 21. 방 단위 오클루전·컬링·수면

### 21.1 UE5에 오클루전 포탈은 없다

Source의 portal, Unity의 Umbra 같은 방 단위 가시성 시스템은 UE5에 없다. 대신 프러스텀 + HZB 오클루전 + Nanite 소프트웨어 래스터가 화면에 안 보이는 것을 자동으로 거른다. 문제는 **보이지만 비용이 큰 것**(문 너머로 보이는 실내 전체)과 **그려지지만 필요 없는 것**(먼 방의 라이트·오디오·틱)이다. 자세한 비교는 [오픈월드 콘텐츠 가이드 3.4절](open_world_content_and_architecture_guide.md)에 있다.

### 21.2 네 단계로 끊는다

| 목적 | 수단 | 단위 |
| --- | --- | --- |
| 로드하지 않기 | Level Instance(건물), Data Layer(층·구역) | 건물 / 층 |
| 그리지 않기 | Nanite + HZB, `Cull Distance Volume`, `Max Draw Distance` | 프리미티브 |
| 계산하지 않기 | 방 볼륨 라이트·오디오·틱 토글 | 방 |
| 미리 계산하기 | `Precomputed Visibility Volume`(모바일·정적) | 방 |

### 21.3 방 수면(sleep) 상태 머신

```
Active   : 플레이어가 방 안. 라이트·틱·오디오·AI 전부 켜짐
Warm     : 문 너머 6~10 m. 라이트 켜짐, AI 틱 유지, 오디오 감쇠
Sleep    : 10 m 밖 또는 벽 2장 너머. 라이트 끔, AI 틱 정지, 오디오 존 비활성
```

```cpp
// ARoomVolume: 방 단위 수면 관리 ([오픈월드 콘텐츠 가이드 3.4절] 코드의 확장)
void ARoomVolume::UpdateSleepState(const FVector& ListenerLocation)
{
    const float DistSq = FVector::DistSquared2D(ListenerLocation, GetActorLocation());

    ERoomState Desired = ERoomState::Sleep;
    if (DistSq <= FMath::Square(ActiveRadius))      { Desired = ERoomState::Active; }
    else if (DistSq <= FMath::Square(WarmRadius))   { Desired = ERoomState::Warm; }

    if (Desired == CurrentState) { return; }

    // 라이트는 Warm까지만 유지, 틱은 Active에서만
    for (ULightComponent* Light : ManagedLights)
    {
        if (Light) { Light->SetVisibility(Desired != ERoomState::Sleep); }
    }
    for (AActor* Actor : ManagedActors)
    {
        if (Actor)
        {
            Actor->SetActorTickEnabled(Desired == ERoomState::Active);
            Actor->SetActorHiddenInGame(false);   // 콜리전은 항상 유지
        }
    }
    CurrentState = Desired;
}
```

핵심은 **콜리전은 절대 끄지 않는 것**이다. 라이트와 틱만 끄고 메시는 남겨 두어야 플레이어가 벽을 통과하지 않는다. 그리고 문 너머로 보이는 방은 Sleep으로 두면 안 된다(불이 꺼져 있으면 바로 티가 난다).

### 21.4 시야를 설계로 끊는다

컬링은 하드웨어에 맡기되, **문 너머로 보이는 양**은 레벨 디자인으로 줄인다.

- 문을 복도 축에서 15~30도 틀어 단다. 정면으로 마주 보면 방 전체가 보인다.
- 방 입구에 벽감(vestibule)을 둔다. 문 앞 1.2 m의 좁은 공간이 시야를 자른다.
- 큰 방은 기둥·칸막이로 3~4개 구역으로 나눈다. 한 번에 한 구역만 보이게.
- 계단은 난간 벽으로 다음 층을 가린다.

### 21.5 오디오도 방 단위로

`Audio Volume`(리버브) + `Occlusion` + 감쇠 거리. 방이 Sleep이면 그 방의 환경음 액터도 틱을 끈다. 복도 소리가 방 안까지 들리면 공간감이 무너진다.

---

## 22. 예산표와 프로파일링

### 22.1 실내 예산(60 fps, 1440p 기준의 작성 예)

| 항목 | PC(중급) | 콘솔 | 측정 |
| --- | --- | --- | --- |
| 드로우 서브미션 | < 5,000 | < 4,000 | `stat scenerendering` |
| 화면 삼각형(Nanite 포함) | 예산 없음(픽셀 비용) | 예산 없음 | `stat rhi` |
| 방당 동적 광원 | 5 | 4 | 라이트 컴포넌트 수 |
| 방당 그림자 광원 | 2 | 2 | `stat shadowrendering` |
| 반투명 면적 | 화면의 15% 이하 | 10% 이하 | `stat gpu` |
| 방당 소품 개체 | 80 | 64 | 배치 도구 |
| 텍스처 풀 | 3.5 GB | 2.5 GB | `stat streaming` |
| Lumen 씬 업데이트 | 2~3 ms | 2~3 ms | `ProfileGPU` |

### 22.2 프로파일링 순서

```
1. stat unit            -> Game / Draw / GPU 중 어디가 병목인가
2. stat scenerendering  -> 드로우 서브미션, 메시 수
3. stat shadowrendering -> 그림자 캐스팅 광원 수
4. stat gpu             -> 라이팅·포스트 비용 (Lumen, VSM)
5. ProfileGPU           -> 한 프레임 상세 (Lumen Scene, Base Pass)
6. Lumen > Visualization > Surface Cache / Lumen Scene  -> 커버리지·누광
7. stat streaming       -> 텍스처 풀 초과
```

### 22.3 실내에서 자주 보는 지표

| 지표 | 정상 | 위험 |
| --- | --- | --- |
| Base Pass | 3~6 ms | 10 ms 이상 — 소품 머티리얼 수 과다 |
| Lumen Scene | 1~3 ms | 5 ms 이상 — 방 수·카드 수 과다 |
| Shadows | 2~4 ms | 6 ms 이상 — 그림자 광원 과다 |
| Translucency | 1~2 ms | 4 ms 이상 — 유리·연기·데칼 남용 |
| Draw | 4~8 ms | 12 ms 이상 — 드로우 서브미션 폭증 |

---

## 23. 자주 터지는 지점

| 증상 | 원인 | 확인 | 처방 |
| --- | --- | --- | --- |
| 문을 지날 때 화면이 확 당긴다 | SpringArm이 문틀에 충돌 | `ProbeChannel`, 문틀 콜리전 | 문틀 Camera Ignore, 문 트리거에서 암 140 |
| 좁은 복도에서 화면이 벽으로 가득 | 암이 벽에 붙음 | `camera` 명령의 free_yaw | 복도 40 cm 확장 또는 FOV 96 |
| 캐릭터가 벽에 끼어 진동 | 캡슐 반경 과다 | 캡슐 34 vs 복도 | 복도 120 이상, 캡슐 32로 |
| 계단에서 캐릭터가 튄다 | 단별 콜리전 + `MaxStepHeight` 경계 | 단높이 18, 스텝 45 | 경사 콜리전 또는 단 콜리전 정리 |
| 3단 계단을 못 오른다 | `MaxStepHeight` 45 < 54 | 계단 묶음 메시 | 단별 콜리전, 경사 램프 |
| 문 위에서 머리가 걸린다 | 상인방 여유 부족 | 문 220 - 캐릭터 176 | 문 240, 계단 위 문은 +단높이 |
| 벽 너머 빛이 샌다 | 벽 두께 < 거리 필드 복셀 | Lumen Surface Cache | 벽 15 cm, 양면 메시 제거 |
| 실내가 회색으로 뜬다 | 서피스 캐시 미커버 | Lumen 시각화 분홍 | 메시 단순화, 카드 수 |
| 그림자가 사라진다 | VSM 페이지 부족 | `stat shadowrendering` | 그림자 광원 2개 이하 |
| 손전등이 벽을 뚫는다 | Near Clip·스폰 위치 | 카메라 앞 50 cm | Near 5, 스폰 오프셋 |
| 방에 들어가면 프레임이 반토막 | 라이트·소품·틱 동시 활성 | `stat unit` | 방 수면, 라이트 3~5개 |
| 문 너머 방이 전부 그려진다 | 시야 차단 없음 | HZB 시각화 | 문 각도 15~30도, 벽감 |
| NPC가 문 앞에서 멈춘다 | 내비메시 폴리곤 끊김 | `show Navigation` | 복도 110 이상, 에이전트 반경 30 |
| 발소리가 전부 같다 | Physical Material 미지정 | 메시 Phys Material | 표면 타입 9종 매핑 |
| 데칼이 깜빡인다 | z-fighting | 데칼 각도·오프셋 | 1~2도 기울임, 2 cm 띄움 |
| 소품이 벽을 뚫고 보인다 | Nanite + 얇은 벽 | 메시 바운드 | 벽 두께, 소품 배치 간격 |
| 방마다 똑같아 보인다 | 같은 각도·같은 소품 | 스크린샷 비교 | 회전·스케일·색·주변 교체 |
| 텍스트를 안 읽는 것 같다 | 노트가 어둡거나 멀다 | 플레이테스트 | 조명·위치·3~5문장 |
| 분위기가 안 산다 | 발소리·환경음 없음 | 오디오 믹스 | Physical Material + 리버브 존 |
| 로딩 중 문이 열려 있다 | Level Instance 경계 | WP 셀 경계 | 건물 단위 묶음, Data Layer |

---

## 24. 참고 자료

**엔진 (Epic 공식)**

- Character Movement Component — `MaxStepHeight` 45, `WalkableFloorAngle` 44.765, `CrouchedHalfHeight` 40, `MaxWalkSpeed` 600: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/UCharacterMovementComponent
- `ACharacter` — `BaseEyeHeight` 64, 캡슐 34 x 88: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/ACharacter
- Spring Arm Component — `TargetArmLength`, `ProbeSize` 12, `ProbeChannel`: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/USpringArmComponent
- Lumen Technical Details — 거리 필드·서피스 캐시·누광: https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-technical-details-in-unreal-engine
- Nanite Virtualized Geometry — 클러스터·인스턴싱: https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine
- Physical Materials — 표면 타입과 발소리: https://dev.epicgames.com/documentation/en-us/unreal-engine/physical-materials-in-unreal-engine
- Audio Volumes / Reverb — https://dev.epicgames.com/documentation/en-us/unreal-engine/audio-volumes-in-unreal-engine

**레벨 디자인**

- The Level Design Book — Metrics (플레이어/건축 지표, 엔진별 치수, 카메라 높이·FOV): https://book.leveldesignbook.com/process/blockout/metrics
- The Level Design Book — Environmental Storytelling (환경 서사·연출·플롯형 레벨): https://book.leveldesignbook.com/process/env-art/storytelling
- GameDesign.gg — Environmental Storytelling in Level Design (before/after, 3단서+1질문, 텍스트 제거 테스트): https://gamedesign.gg/articles/environmental-storytelling-in-level-design/
- Conger He, *Best Practices: Using Semiotics in Environmental Storytelling*, SMU Guildhall, 2024 — 기호학·80% 이해 규칙: https://scholar.smu.edu/cgi/viewcontent.cgi?article=1009&context=guildhall_leveldesign_etds
- Harvey Smith & Matthias Worch, GDC 2010 — 환경 서사의 정의와 White Space Storytelling (위 논문에서 인용)

**건축·인간공학**

- 건축물의 피난·방화구조 등의 기준에 관한 규칙 제15조(계단) — 단높이 18/단너비 24~26, 유효높이 210, 계단참 120, 경사로 1:8: https://www.law.go.kr
- 같은 규칙 제15조의2(복도) — 복도 유효너비 120 이상: https://www.law.go.kr
- 주택건설기준 등에 관한 규정 제16조·제18조 — 계단 120/18/26, 난간 120(옥내 90), 간살 10
- François Blondel, *Cours d'architecture* (1675–83) — 2R+T = 보폭(60~66 cm)
- Ernst Neufert, *Architects' Data* — 문·계단·가구·설비의 실측 치수
- Arma Reforger Environment Metrics — 문 125 x 237, 천장 270~330, 벽 20~40: https://community.bistudio.com/wiki/Arma_Reforger:Environment_Metrics
- World of Level Design — UE5 Player Scale & Environment Dimensions: https://worldofleveldesign.com/categories/ue5/guide-to-scale-dimensions-proportions.php

**조명·렌더링**

- Lumen SIGGRAPH 2022 (Wright et al.) — 얇은 메시 SDF 누광과 카드: https://advances.realtimerendering.com/s2022/SIGGRAPH2022-Advances-Lumen-Wright%20et%20al.pdf
- NVIDIA UE5 Raytracing Guide v5.4 — 서피스 캐시·모듈러 조립 권장: https://dlss.download.nvidia.com/uebinarypackages/Documentation/UE5+Raytracing+Guideline+v5.4.pdf
- Epic 개발자 포럼, Nanite ISM/HISM 권장 (2025-09): https://forums.unrealengine.com/t/questions-on-best-practices-for-nanite-lod-interaction-and-ism-hism-combination/2672255

**함께 보는 저장소 문서**

- [open_world_content_and_architecture_guide.md](open_world_content_and_architecture_guide.md) — 모듈러 킷, 루멘 누광, 인간공학 7장, 인게임 건축
- [open_world_creation_pipeline.md](open_world_creation_pipeline.md) — 월드 파티션, PCG, 라이팅, HLOD
- [pbr_material_pipeline.md](pbr_material_pipeline.md) — 트림 시트, 데칼, 채널 패킹
- [unreal_character_and_customization_guide.md](unreal_character_and_customization_guide.md) — 캐릭터·카메라 컴포넌트

**주의**: 이 문서의 수치는 계획용 출발점이다. 플레이어 캡슐·속도·카메라·아트 스타일이 다르면 최적값도 달라진다. 9장의 metrics zoo에서 실제로 걸어 보고, `pipeline/indoor_metric_helper.py`로 검산한 뒤 프로젝트 규약표에 확정값을 적는다. 엔진 기본값은 버전에 따라 바뀌므로 릴리스 노트와 소스에서 확인한다.
