# 오픈월드 콘텐츠 제작·배치와 건축 설계 매뉴얼

> 대상: C++/그래픽스 배경으로 UE5 오픈월드의 콘텐츠(탈것·아이템·건물·배경)를 직접 만드는 개발자
> 범위: **Part 1** 탈것 / 아이템 / 건물 / 배경의 제작·배치 파이프라인 → **Part 2** 건축학 용어·도면·설계 방법론과 게임 스케일 변환
> 기준 시점: **2026-11. Unreal Engine 5.8** 기준. 5.7/5.8에서 Experimental로 표기된 기능은 본문에 그렇게 적었다.
> 함께 읽는 문서: [오픈월드 제작 파이프라인](open_world_creation_pipeline.md)(좌표계·월드 파티션·PCG·라이팅·HLOD) · [PBR 머티리얼 파이프라인](pbr_material_pipeline.md)(텍스처·ORM·트림 시트) · [캐릭터 제작·커스터마이징 가이드](unreal_character_and_customization_guide.md)
> 함께 쓰는 코드: [`examples/unreal_cpp_character/ModularCharacter.h`](../examples/unreal_cpp_character/ModularCharacter.h) · [`pipeline/open_world_helper.py`](../pipeline/open_world_helper.py)

---

## 목차

**Part 1 — 콘텐츠 제작과 배치**

0. [한눈에: 콘텐츠는 "규약 → 예산 → 조립 → 검증" 순서로 만든다](#0-한눈에-콘텐츠는-규약--예산--조립--검증-순서로-만든다)
1. [탈것(Vehicles)](#1-탈것vehicles)
2. [아이템과 상호작용물](#2-아이템과-상호작용물)
3. [건축물: 모듈러 킷과 실내·외 렌더링](#3-건축물-모듈러-킷과-실내외-렌더링)
   - [3.8 인게임 건축 시스템(런타임 건설)](#38-인게임-건축-시스템런타임-건설)
   - [3.9 건물 디테일 표현 기법](#39-건물-디테일-표현-기법)
4. [배경과 레벨 드레싱](#4-배경과-레벨-드레싱)

**Part 2 — 건축 설계**

5. [건축학 전문용어](#5-건축학-전문용어)
6. [도면의 종류와 도면 규약](#6-도면의-종류와-도면-규약)
7. [인간공학 치수 vs 게임 스케일](#7-인간공학-치수-vs-게임-스케일)
8. [모듈러 건축 설계 방법론](#8-모듈러-건축-설계-방법론)
9. [제작 로드맵과 검증 게이트](#9-제작-로드맵과-검증-게이트)
10. [자주 터지는 지점](#10-자주-터지는-지점)
11. [참고 자료](#11-참고-자료)

---

## 0. 한눈에: 콘텐츠는 "규약 → 예산 → 조립 → 검증" 순서로 만든다

오픈월드에서 콘텐츠 하나(차 한 대, 건물 한 채, 아이템 300종)를 만드는 일은 모델링이 아니라 **규약을 정하고 그 규약 위에서 조립하는 일**이다. 규약이 없으면 300번째 에셋에서 반드시 무너진다. 실제로 무너지는 지점은 대개 다음 네 곳이다.

```
① 규약 없음      피벗이 제각각 → 배치할 때마다 손으로 띄운다
                 스케일이 제각각 → 문 앞에서 캐릭터가 걸린다
② 예산 없음      소품 하나가 머티리얼 5장 → 드레싱 1,000개에서 드로우콜 폭발
③ 조립 규칙 없음  건물 킷이 안 붙는다 → 2주 뒤 킷을 다시 만든다
④ 검증 없음      60 fps에서만 돌아간다 → 기기 프로파일에서 프레임이 반으로 준다
```

Part 1의 각 장은 이 네 항목을 콘텐츠 유형별로 채우는 순서다.

### 0.1 다섯 가지 공통 원칙

1. **월드 단위는 1 uu = 1 cm로 고정한다.** 모든 DCC 작업과 도면은 cm로 끝낸다. 블렌더에서 m로 작업했다면 익스포트 시 스케일을 반드시 확인한다(가장 흔한 실패: 100배 또는 1/100). [오픈월드 제작 파이프라인](open_world_creation_pipeline.md) 1.1절의 Large World Coordinates 규칙과 함께 본다.
2. **피벗과 스냅 기준점을 에셋 규약으로 문서화한다.** 피벗은 "바닥 중앙"이 기본, 벽·문은 "하단 좌측 모서리", 차량은 "차체 중심 + 지면 접점"처럼 유형별로 고정한다.
3. **콘텐츠 유형마다 수치 예산을 정한다.** 삼각형·머티리얼 슬롯·텍스처 MB·드로우콜·애니메이션 비용. 예산의 합이 프레임 예산을 넘지 않게 기능을 거래한다.
4. **Nanite와 LOD는 콘텐츠 성격으로 결정한다.** 정적 프랍·건축물은 Nanite, 스키닝 캐릭터·차량·모바일은 LOD. 판단표는 [블렌더 파이프라인](blender_pipeline.md) 0장.
5. **배치도 데이터다.** 손으로 레벨에 흩뿌린 소품은 나중에 규칙을 못 바꾼다. PCG 그래프·데이터 테이블·스폰 볼륨처럼 "다시 돌릴 수 있는" 형태로 배치한다.

### 0.2 공통 규약표 (프로젝트 시작 시 채워 고정할 것)

| 항목 | 규약 예시 | 비고 |
| --- | --- | --- |
| 단위 | 1 uu = 1 cm | DCC 임포트 스케일 1.0 확인 |
| 월드 그리드 | 100 cm (10 uu/칸), 세부 10 cm | 건축 키트는 100 cm 배수 |
| 피벗 | 바닥 중앙(Z=0) | 벽/문은 하단 좌측 모서리 |
| 정면 방향 | +X | DCC에서 -Y 정면이면 임포트 시 회전 보정 |
| 에셋 명명 | `SM_`, `SK_`, `M_`, `MI_`, `T_`, `BP_`, `DA_`, `PCG_` | 접두어 없는 파일은 반려 |
| 텍셀 밀도 | 히어로 512 px/m, 일반 256, 배경 128 | 같은 화면에 두 밀도가 붙으면 티가 난다 |
| 머티리얼 슬롯 | 프랍 ≤ 2, 건축 모듈 1 (트림 시트) | 슬롯 수 = 드로우콜 |
| 충돌 | 단순 콜리전(UCX) 별도 생성, 복잡도 ≤ 32 삼각형 | Nanite 메시는 폴리 콜리전을 쓸 수 없다 |
| LOD | 0/1/2/3, 화면 점유율 1.0/0.5/0.25/0.1 | Nanite는 LOD 무시(폴리지·마스크 제외) |
| 라이트맵 | 동적 라이팅 전제면 불필요 | 정적 베이크 구역만 UV2 생성 |

### 0.3 콘텐츠 유형별 예산 (PS5/XSX·60 fps·1440p 기준의 작성 예시)

| 유형 | 삼각형(LOD0) | 머티리얼 슬롯 | 텍스처 | 화면 내 동시 수 | 비고 |
| --- | --- | --- | --- | --- | --- |
| 건축 모듈(벽 4 m) | 1k~3k (Nanite 원본 20k까지 허용) | 1 | 1 세트(트림 시트 공유) | 200~400 | Nanite + HISM/LI 조합 |
| 건물(한 채, 모듈 40개) | 모듈 합계 | 1~2 | 공유 | 3~8 시야 | HLOD 프록시 필수 |
| 도시 소품(크레이트·통) | 300~1.5k | 1 | 128~256 px/m | 500~2,000 | HISM 필수 |
| 히어로 프랍(아이템) | 5k~30k (Nanite) | 1~2 | 512 px/m | 10~30 | LOD 없이 Nanite 가능 |
| 픽업 아이템(월드 드롭) | 200~800 | 1 | 128 | 50~200 | 인스턴싱, 회전 애니메이션은 셰이더로 |
| 탈것(플레이어) | 40k~120k | 3~5 | 512 px/m | 1~4 | 스키닝 + 물리 |
| 탈것(NPC 교통) | 8k~20k | 1~2 | 256 | 10~40 | 원경은 프록시 메시 |
| NPC(주요) | 30k~80k | 3~6 (모듈러) | 512 | 5~15 | LOD 4단 |
| NPC(군중) | 8k~15k | 1~2 | 256 | 30~100 | MassCrowd/Vertex Anim |

이 표를 채운 뒤, 어떤 콘텐츠를 추가할 때마다 "어느 줄에서 비용을 빼는지"를 먼저 정한다. 이 저장소의 `open_world_helper.py checklist`가 이 표를 검사 항목으로 갖고 있다.

---

## 1. 탈것(Vehicles)

### 1.1 무엇으로 만들지 먼저 정한다

| 방식 | 적합한 대상 | 장점 | 비용·한계 |
| --- | --- | --- | --- |
| **Chaos Vehicles (WheeledVehicle)** | 자동차·오토바이·버기·트럭 | 서스펜션·엔진·변속·타이어 마찰이 한 컴포넌트에 통합. 튜닝 파라미터가 물리적으로 의미 있다 | 바퀴는 스켈레톨 메시의 물리 본에 붙는다. 차체 변형·모듈 조립은 직접 |
| **Chaos Modular Vehicles**(5.5+, Experimental) | 파츠 조립형 차량(부품 교체·파괴) | 클러스터 유니온 기반 조립, 바퀴·차체 파츠를 런타임에 교체 | Experimental. 리플리케이션·성능 안정성 리스크를 일정에 넣어야 한다 |
| **일반 물리 + 커스텀 힘** | 호버크래프트·비행체·보트·궤도차 | 자유도가 가장 높다 | 서스펜션·마찰·변속을 직접 구현. 네트워크 예측도 직접 |
| **애니메이션 기반(고정 경로)** | 기차·케이블카·페리·컨베이어 | 결정적이고 저렴하다 | 상호작용 자유도 없음 |
| **부분 시뮬레이션(애니메이션 + 트레이스)** | 원경 교통량, 배경 차량 | 1/10 비용 | 플레이어가 탈 수 없다 |

결정 규칙: **플레이어가 조작하고 물리 반응이 게임플레이에 영향을 주면 Chaos Vehicles**, 조작 없이 움직이기만 하면 애니메이션/스플라인, 물리 특성이 비표준(호버·비행)이면 커스텀 힘이다. 한 오픈월드에서 이 셋을 섞는 것이 정상이며, 문제는 섞는 기준을 정하지 않는 것이다.

### 1.2 메시 규약: 바퀴가 붙는 자리

Chaos Wheeled Vehicle은 차체 스켈레탈 메시의 **물리 본(physics bone)** 위치에 바퀴를 만든다. 따라서 차체 메시는 반드시 다음 규약을 지킨다.

| 요소 | 규약 | 이유 |
| --- | --- | --- |
| 차체 | `SK_Vehicle_Sedan` (스켈레탈 메시) | 바퀴 부착점을 본으로 갖는다 |
| 바퀴 본 | `Phys_Wheel_FL`, `FR`, `RL`, `RR` (좌표계는 차량 로컬) | `FChaosWheelSetup::BoneName`이 이 이름을 참조 |
| 바퀴 메시 | `SK_Wheel_Sedan` (스켈레탈 또는 스태틱) | `UChaosVehicleWheel` 서브클래스가 참조 |
| 본 계층 | 바퀴 본은 루트의 직계 자식 | 차체 애니메이션(서스펜션 시각 효과)이 바퀴에 영향 주지 않게 |
| 원점 | 지면 접점 Z=0, 차체 중심 X=0 | 스폰 시 바퀴가 땅에 박히는 문제 방지 |
| 질량 | 차체 스켈레탈 메시 `Mass` = 실제 차량 질량(kg)과 일치 | 서스펜션 스프링레이트 계산의 기준 |

주의: 차체 질량을 작게 넣으면(예: 기본 100) 서스펜션이 폭발한다. Chaos는 `Mass`로 스프링 정지 하중을 계산하고, 질량이 1 kg 미만이면 `ensure`로 경고한다.

### 1.3 컴포넌트 셋업: 파라미터를 물리량으로 읽기

`UChaosWheeledVehicleMovementComponent`의 설정은 네 덩어리다. 각 값이 **물리량**이므로, 숫자를 감으로 넣지 말고 다음 관계로 계산한다.

```
바퀴 1개 정지 하중  = 질량 × 중력가속도 / 바퀴 수      (예: 1,500 kg → 3,675 N/바퀴)
서스펜션 고유진동수  f = (1/2π)·√(k/m_sprung)          (승용차 1.2~2.0 Hz)
감쇠비              ζ  = c/(2√(k·m))                   (승용 0.25~0.4, 스포츠 0.4~0.6, 오프로드 0.15~0.25)
엔진 출력           P(kW) = 2π · MaxTorque · RPM@maxTorque / 60 / 1000
차속(이론)          v = RPM / (FinalRatio · GearRatio) · (2π · WheelRadius) / 60
```

#### Engine Setup (`FVehicleEngineConfig`)

| 필드 | 의미 | 승용차 예시 | 트럭 예시 | 비고 |
| --- | --- | --- | --- | --- |
| `TorqueCurve` | 정규화 토크(0~1) vs RPM | 1,000 rpm 0.55 → 4,000 rpm 1.0 → 6,500 rpm 0.75 | 800 rpm 0.9 → 1,800 rpm 1.0 | 곡선이 직선이면 "전기 모터"처럼 느껴진다 |
| `MaxTorque` | 최대 토크(Nm) | 300~420 | 1,200~2,000 | 곡선의 1.0에 곱해진다 |
| `MaxRPM` | 최대 회전수 | 6,500 | 2,400 | 변속 기준점과 함께 본다 |
| `EngineIdleRPM` | 공회전 | 800 | 600 | |
| `EngineBrakeEffect` | 스로틀 해제 시 엔진 브레이크 | 0.05 | 0.15 | 내리막에서 속도가 줄지 않으면 올린다 |
| `EngineRevUpMOI` | 회전 관성(가속감) | 5 | 15 | 낮으면 즉각 반응(아케이드) |
| `EngineRevDownRate` | 감속률 | 600 | 600 | |

#### Transmission Setup (`FVehicleTransmissionConfig`)

| 필드 | 의미 | 예시 |
| --- | --- | --- |
| `bAutomaticTransmission` | 자동/수동 | 아케이드는 true |
| `bAutomaticReverse` | 정지 상태 브레이크 유지로 후진 | true |
| `FinalRatio` | 최종 감속비 | 3.08 (스포츠 3.7~4.1) |
| `ForwardGearRatios` | 전진 기어비 배열 | `[3.2, 2.1, 1.5, 1.15, 0.9]` |
| `ReverseGearRatios` | 후진 | `[3.0]` |
| `ChangeUpRPM` / `ChangeDownRPM` | 변속 임계 | 6,000 / 2,200 — `MaxRPM`보다 낮아야 변속이 된다 |
| `GearChangeTime` | 변속 시간(s) | 0.3~0.5 (듀얼클러치 0.15) |
| `TransmissionEfficiency` | 전달 효율 | 0.9 |

"자동인데 기어가 안 바뀐다"의 90%는 `ChangeUpRPM > MaxRPM`이거나 `ForwardGearRatios`가 비어 있는 경우다.

#### Differential Setup (`FVehicleDifferentialConfig`)

`DifferentialType`: Undefined / AllWheelDrive / FrontWheelDrive / RearWheelDrive. `FrontRearSplit`은 AWD에서만 의미가 있고 0이면 전륜, 1이면 후륜 100%다. 드리프트 중심 게임은 후륜 + 낮은 `LimitedSlip` 감각(타이어 마찰·슬립 그래프로 조절)이 기준이다.

#### Steering Setup (`FVehicleSteeringConfig`)

| 필드 | 의미 | 비고 |
| --- | --- | --- |
| `SteeringType` | SingleAngle / AngleRatio / Ackermann | 실제 회전 반경을 원하면 Ackermann |
| `AngleRatio` | AngleRatio 모드에서 외측 바퀴 배율 | 0.6~0.8 |
| `SteeringCurve` | 속도별 최대 조향 배율 | **X축이 mph**다. km/h로 착각하면 고속에서 조향이 과하다 |

#### Wheel Setups (`TArray<FChaosWheelSetup>`)

`WheelClass`(`TSubclassOf<UChaosVehicleWheel>`) + `BoneName` + `AdditionalOffset`. 통상 앞좌/앞우/뒤좌/뒤우 4개이며, 6륜은 6개. 런타임에 바퀴를 교체하려면 `WheelSetups[i]`를 바꾸고 `ResetVehicle()`을 호출한다(차량 상태가 초기화되므로 주행 중 교체는 연출과 함께).

`UChaosVehicleWheel` 주요 값:

| 카테고리 | 값 | 의미 | 승용차 예시 |
| --- | --- | --- | --- |
| 형상 | `WheelRadius`, `WheelWidth`, `WheelMass` | 반경/폭/질량 | 35 / 25 / 20 kg |
| 조향 | `MaxSteerAngle`, `bAffectedBySteering` | 최대 조향각 | 35° (앞바퀴만) |
| 제동 | `MaxBrakeTorque`, `MaxHandbrakeTorque`, `bAffectedByBrake`, `bAffectedByHandbrake` | 제동 토크 | 3,000 / 4,000 Nm |
| 구동 | `bAffectedByEngine` | 구동륜 여부 | 후륜만 true |
| 서스펜션 | `SuspensionAxis`, `SuspensionMaxRaise`, `SuspensionMaxDrop` | 스트로크 | 10 / 15 cm |
| 서스펜션 | `SuspensionNaturalFrequency`, `SuspensionDampingRatio` | Hz, ζ | 1.5 Hz / 0.35 |
| 서스펜션 | `SuspensionForceOffset`, `SweepType` | 힘 작용점, 트레이스 방식 | `Simple` (비용) vs `Complex` |
| 마찰 | `FrictionForceMultiplier`, `SlipGraph` 계열 | 타이어 마찰·슬립 | 1.0 기준, 표면별 배율은 물리 머티리얼로 |

### 1.4 C++: 차량 서브클래스를 만들고 데이터로 튜닝한다

차량마다 블루프린트를 복제하지 말고, 한 C++ 클래스에 **데이터 테이블 행**을 먹인다. 튜닝 값이 데이터로 빠지면 밸런싱과 회귀 검증이 가능해진다.

```cpp
// VehicleTuningRow.h
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "VehicleTuningRow.generated.h"

/** 차량 1종의 튜닝 값. 데이터 테이블 행으로 관리한다. */
USTRUCT(BlueprintType)
struct FVehicleTuningRow : public FTableRowBase
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, Category = "Engine")   float MaxTorque = 380.f;
    UPROPERTY(EditAnywhere, Category = "Engine")   float MaxRPM = 6500.f;
    UPROPERTY(EditAnywhere, Category = "Engine")   float EngineIdleRPM = 850.f;
    UPROPERTY(EditAnywhere, Category = "Engine")   float EngineBrakeEffect = 0.06f;

    UPROPERTY(EditAnywhere, Category = "Transmission") float GearChangeTime = 0.35f;
    UPROPERTY(EditAnywhere, Category = "Transmission") float ChangeUpRPM = 5900.f;
    UPROPERTY(EditAnywhere, Category = "Transmission") float ChangeDownRPM = 2200.f;
    UPROPERTY(EditAnywhere, Category = "Transmission") TArray<float> ForwardGearRatios = { 3.2f, 2.1f, 1.5f, 1.15f, 0.9f };

    UPROPERTY(EditAnywhere, Category = "Suspension") float NaturalFrequency = 1.5f;
    UPROPERTY(EditAnywhere, Category = "Suspension") float DampingRatio = 0.35f;
    UPROPERTY(EditAnywhere, Category = "Suspension") float MaxRaise = 10.f;
    UPROPERTY(EditAnywhere, Category = "Suspension") float MaxDrop = 15.f;
};
```

```cpp
// TunedVehiclePawn.cpp (발췌)
#include "TunedVehiclePawn.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Engine/DataTable.h"

void ATunedVehiclePawn::ApplyTuning(const FVehicleTuningRow& Row)
{
    UChaosWheeledVehicleMovementComponent* Movement =
        Cast<UChaosWheeledVehicleMovementComponent>(GetVehicleMovementComponent());
    if (!Movement)
    {
        UE_LOG(LogTemp, Error, TEXT("ChaosWheeledVehicleMovementComponent가 없습니다: %s"), *GetName());
        return;
    }

    // 1) 엔진·변속·구동계
    Movement->EngineSetup.MaxTorque      = Row.MaxTorque;
    Movement->EngineSetup.MaxRPM         = Row.MaxRPM;
    Movement->EngineSetup.EngineIdleRPM  = Row.EngineIdleRPM;
    Movement->EngineSetup.EngineBrakeEffect = Row.EngineBrakeEffect;

    Movement->TransmissionSetup.GearChangeTime  = Row.GearChangeTime;
    Movement->TransmissionSetup.ChangeUpRPM     = Row.ChangeUpRPM;
    Movement->TransmissionSetup.ChangeDownRPM   = Row.ChangeDownRPM;
    Movement->TransmissionSetup.ForwardGearRatios = Row.ForwardGearRatios;

    // 2) 바퀴별 서스펜션. SetSuspensionParams는 각 바퀴의 스프링을 개별 설정한다.
    for (int32 WheelIndex = 0; WheelIndex < Movement->Wheels.Num(); ++WheelIndex)
    {
        Movement->SetSuspensionParams(
            /*Rate*/    Row.NaturalFrequency,
            /*Damping*/ Row.DampingRatio,
            /*Preload*/ 0.f,
            /*MaxRaise*/ Row.MaxRaise,
            /*MaxDrop*/  Row.MaxDrop,
            WheelIndex);
    }

    // 3) 파라미터를 물리 엔진에 반영
    Movement->ResetVehicle();
}
```

주의: `ResetVehicle()`은 차량을 스폰 위치로 되돌리고 속도를 0으로 만든다. 주행 중 튜닝 갱신에는 쓰지 말고, 스폰 직후나 정비소 진입 시점에만 호출한다.

### 1.5 네트워크: 차량은 "예측되는 캐릭터"가 아니다

`UCharacterMovementComponent`는 클라이언트 예측 + 서버 보정을 엔진이 제공하지만, **Chaos Vehicle에는 그런 기본 예측이 없다.** 그래서 멀티플레이에서 차량은 다음 세 가지 중 하나를 고른다.

| 방식 | 무엇을 복제하나 | 운전자 경험 | 적합한 경우 | 구현 비용 |
| --- | --- | --- | --- | --- |
| **기본(레거시) 물리 복제** | 액터 트랜스폼 + 속도 보정 | 서버 지연이 그대로 보인다. 60~100 ms에서 핸들이 "늦게" 반응 | 협동 위주, 저지연 서버, 소수 차량 | 없음(`bReplicateMovement`) |
| **Networked Physics: Predictive Interpolation**(5.4+) | 서버 권위 + 예측 보간 | 운전자 입력이 국소 반영되지만 충돌 시 어긋남 | 다른 플레이어가 보는 차량·주변 물체 | 중. `APhysicsReplicationMode=2` |
| **Networked Physics: Resimulation**(5.4+) | 입력 이력 + 물리 재시뮬레이션 | 운전자 예측이 가장 자연스럽다 | 경쟁 레이싱, 차량 전투 | 높음. 히스토리 캐시 CPU/메모리 + 튜닝 난이도 |
| **운전자 권위(비대칭)** | 운전자 시뮬레이션 결과만 전송, 서버는 검증만 | 최고의 반응성 | PvE, 소규모 협동, 부정행위 리스크가 낮은 게임 | 중. 안티치트 포기 또는 별도 검증 |

실무 순서:

1. 먼저 **기본 복제 + `Replicate Physics to Autonomous Proxy` 끄기**로 시작한다. 운전자 로컬 시뮬레이션은 부드럽고, 다른 클라이언트는 서버 결과를 보간해 따라온다. 차량 간 접촉이 게임플레이상 중요하지 않다면 여기서 끝낸다.
2. 차량끼리 부딪히는 것이 핵심이면 **Predictive Interpolation**, 그다음 **Resimulation**으로 올린다. Resimulation은 물리 틱마다 상태를 캐시하므로 차량 수 × 1/RTT 만큼의 CPU·메모리를 예산에 넣는다.
3. 어느 쪽이든 **서버는 입력만 받는다.** 클라이언트가 보낸 트랜스폼을 신뢰하지 않는다. 입력은 `ServerSetThrottle/Steering` 형태의 RPC로, 값은 -1~1 범위로 클램프한다.

```cpp
// 입력은 값이 아니라 "의도"를 보낸다. 서버가 시뮬레이션 주체다.
UFUNCTION(Server, Unreliable)
void ServerSetDrivingInput(float Throttle, float Steering, bool bHandbrake);

void ATunedVehiclePawn::ServerSetDrivingInput_Implementation(float Throttle, float Steering, bool bHandbrake)
{
    UChaosVehicleMovementComponent* Movement = GetVehicleMovementComponent();
    if (!Movement || !HasAuthority()) { return; }

    Movement->SetThrottleInput(FMath::Clamp(Throttle, -1.f, 1.f));
    Movement->SetSteeringInput(FMath::Clamp(Steering, -1.f, 1.f));
    Movement->SetHandbrakeInput(bHandbrake);
}
```

### 1.6 오디오: RPM·기어·슬립을 파라미터로 보낸다

차량 오디오는 샘플 재생이 아니라 **연속 파라미터로 구동되는 신스**다. MetaSound에서 다음 파라미터를 받는다.

| 파라미터 | 원천 | 용도 |
| --- | --- | --- |
| `RPMNormalized` | `GetEngineRotationSpeed() / MaxRPM` | 엔진음 피치·레이어 크로스페이드 |
| `Load` | 스로틀 입력(0~1) | 배기음 밝기, 터보 휘슬 |
| `Gear` | `GetCurrentGear()` | 변속 시 "쿵" 트리거, 기어별 레이어 |
| `SpeedKph` | `GetVelocity().Size() * 0.036` | 풍절음(속도³ 근사), 노면 롤링음 |
| `Slip` | 휠 상태의 슬립/`bIsSkidding` | 타이어 비명, 자갈 튀김 |
| `SurfaceType` | 물리 머티리얼 조회 | 노면별 발소리·타이어음 |

구현 요령:

- **틱마다 `SetFloatParameter`를 직접 호출하지 않는다.** 10~20 Hz로 샘플링해 보간하면 충분하고, 오디오 스레드 부하가 크게 줄어든다.
- 변속음은 `GetCurrentGear()`가 바뀐 프레임에 **원샷**으로 트리거한다. 엔진음 레이어의 피치만 바꾸면 "전기차"처럼 들린다.
- 실내/실외는 별도 믹스 스냅샷(실내 = 저역 강조 + 짧은 리버브, 실외 = 개방)으로 전환한다. 차량 문이 닫히는 순간에 블렌드한다.
- 원경 교통량은 3D 감쇠 대신 **거리 기반 레이어 + 낮은 업데이트율**로 처리한다. 200대의 실제 엔진음을 돌리면 오디오 스레드가 먼저 죽는다.

### 1.7 승하차와 카메라: 게임플레이의 접합부

승하차는 "폰을 바꾸는 일"이지 "메시를 숨기는 일"이 아니다. 표준 흐름은 다음과 같다.

```
[상호작용]  플레이어가 차량에 Interact → 서버 RPC RequestEnterVehicle(Vehicle, SeatIndex)
[검증]      서버: 좌석 비었는지 / 차량 소유·잠금 / 거리(≤ 250 cm) / 상태(파괴·전복) 확인
[바인딩]    PlayerController->Possess(VehiclePawn) 대신:
            - 캐릭터는 AttachToComponent(SeatSocket) + MovementMode = None + 컬리전 끔
            - 카메라는 봄(차량 카메라)으로 전환, 입력 컨텍스트를 Driving IMC로 교체
[복제]      Occupant 목록(SeatIndex → PlayerState)을 서버 권위로 복제
[하차]      좌석 옆 ExitPoint 트레이스로 안전한 지점을 찾아 Detach + Possess(Character)
```

핵심 결정 세 가지:

1. **캐릭터를 계속 소유하되 숨기는가, 차량을 소유하는가.** 전자가 네트워크에서 안정적이다(소유권 이전이 없으므로 RPC 경로·예측이 그대로 유지). 차량은 `APawn`이지만 운전자에게 빙의시키지 않고, 카메라 타깃만 차량으로 바꾼다.
2. **좌석 소켓은 `Seat_DRV`, `Seat_Passenger_01`처럼 소켓 규약을 먼저 정한다.** 소켓 회전까지 맞춰 두면 캐릭터 포즈가 차마다 달라지지 않는다.
3. **하차 지점은 트레이스로 확보한다.** 고정 오프셋으로 내리면 절벽·벽에서 캐릭터가 끼인다. 좌석에서 좌/우 80~120 cm를 캡슐 스윕해 첫 유효 위치를 쓰고, 없으면 차 위로 내린다.

카메라는 차량 카메라 리그(스프링암 + 속도 기반 FOV/암 길이)로 블렌드한다. 승하차 시 0.25~0.4초 블렌드가 없으면 시점이 튄다.

### 1.8 오픈월드 주행 AI: 스플라인 + 조향 제어

NPC 차량이 도로를 따라가게 하는 최소 구성은 **스플라인(경로) + Pure Pursuit(조향) + 속도 프로파일**이다. 내비메시 경로보다 도로 형상에 정확히 붙고, 비용이 낮다.

```
스플라인(도로 중심선, cm 단위)
   → 차량 위치에서 전방 Ld(전방주시거리, 속도 비례 8~25 m) 지점 P 계산
   → 조향 = clamp( 2·sin(α) / Ld , -1, 1 )   (α = 차체 전방과 P의 각도)
   → 목표 속도 = 커브 곡률 기반(곡률 반경 R에서 v_max = √(a_lat·R))
   → 스로틀/브레이크 = PID(목표 속도 - 현재 속도)
```

```cpp
// SplineFollowComponent.cpp (발췌)
void USplineFollowComponent::TickFollow(float DeltaTime)
{
    if (!Spline || !Vehicle) { return; }

    const FVector Location = Vehicle->GetActorLocation();
    // 스플라인에서 가장 가까운 지점의 진행거리로 전방 목표점을 찾는다.
    const float InputKey = Spline->FindInputKeyClosestToWorldLocation(Location);
    const float Distance = Spline->GetDistanceAlongSplineAtSplineInputKey(InputKey);
    const float LookAhead = FMath::Lerp(800.f, 2500.f, FMath::Clamp(SpeedKph / 120.f, 0.f, 1.f));

    const FVector Target = Spline->GetLocationAtDistanceAlongSpline(
        Distance + LookAhead, ESplineCoordinateSpace::World);

    // Pure Pursuit 조향: 차체 전방 기준 좌우 오차를 정규화한다.
    const FVector LocalTarget = Vehicle->GetActorTransform().InverseTransformPosition(Target);
    const float Alpha = FMath::Atan2(LocalTarget.Y, LocalTarget.X);
    const float Steering = FMath::Clamp(2.f * FMath::Sin(Alpha), -1.f, 1.f);

    Vehicle->SetSteeringInput(Steering);
    Vehicle->SetThrottleInput(FMath::Clamp(SpeedPid.Update(DeltaTime, TargetSpeedKph, SpeedKph), -1.f, 1.f));
}
```

대규모 교통량은 두 단계로 나눈다.

- **근거리(50~150 m 내, 10~40대)**: 실제 액터 + Chaos Vehicle + 단순화된 서스펜션(또는 스플라인 이동 + 타이어 애니메이션).
- **원거리**: 애니메이션/스플라인 액터 또는 MassTraffic 방식(도시 규모 교통 시뮬레이션). 원거리는 차량 간 상호작용이 없어도 된다. CitySample의 MassTraffic은 이 분리의 레퍼런스 구현이다.

플레이어와의 충돌이 필요한 근거리만 실제 물리 차량으로 두는 것이 정석이다. 원거리 차량이 플레이어 쪽으로 접근하면 그 시점에 실제 차량 액터로 **승격(promote)**하고, 멀어지면 강등한다.

### 1.9 차량에서 자주 터지는 것

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 스폰하자마자 폭발·요동 | 차체 `Mass`가 비현실적으로 작다, 바퀴 본이 지면 아래 | 질량 실제값, 원점 Z=0, `SuspensionMaxRaise` 확인 |
| 바퀴가 차체에 파묻힘 | `SuspensionForceOffset` 미설정, 바퀴 반경 오타 | 오프셋 = 서스펜션 상단 위치, 반경은 cm |
| 고속에서 조향이 과함 | `SteeringCurve`가 mph 기준인데 km/h로 작성 | 커브 X축 단위 확인 |
| 기어가 안 바뀜 | `ChangeUpRPM > MaxRPM`, 기어비 배열 비어 있음 | |
| 클라이언트에서 차체가 떨림 | 물리 복제 + 서스펜션 디테일 충돌 | 운전자 권위 또는 Networked Physics 모드 |
| 30 cm 턱에서 차가 멈춤 | 바퀴 콜리전이 턱을 못 넘음, `SweepType=Simple` | 턱을 램프로(경사 1:4), 또는 휠 트레이스 응답 조정 |
| 차가 미끄러지지 않고 회전 | 후륜 마찰 과다 | `FrictionForceMultiplier` 하향, 슬립 그래프 조정 |

---

## 2. 아이템과 상호작용물

### 2.1 데이터 주도: 블루프린트 300개 대신 데이터 행 300개

오픈월드 아이템은 종류가 많고 대부분 차이가 "수치와 참조"뿐이다. 그래서 아이템 정의는 **`UPrimaryDataAsset` + `AssetManager` 스캔**으로 만든다. 블루프린트로 만들면 300개 에셋을 각각 열어야 하고, 대량 검증(중복 ID, 누락 아이콘)이 불가능해진다.

```cpp
// ItemDefinition.h
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "GameplayTagContainer.h"
#include "ItemDefinition.generated.h"

class UStaticMesh;
class UTexture2D;
class UGameplayAbility;
class UGameplayEffect;

UENUM(BlueprintType)
enum class EItemRarity : uint8
{
    Common, Uncommon, Rare, Epic, Legendary
};

/** 하나의 아이템 정의. 에셋 매니저가 스캔해 PrimaryAssetId로 조회한다. */
UCLASS(BlueprintType)
class MYGAME_API UItemDefinition : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    /** 게임 로직이 참조하는 안정 ID. 리네임 금지. */
    UPROPERTY(EditDefaultsOnly, Category = "Identity")
    FName ItemId;

    UPROPERTY(EditDefaultsOnly, Category = "Identity")
    FText DisplayName;

    UPROPERTY(EditDefaultsOnly, Category = "Identity")
    FText Description;

    UPROPERTY(EditDefaultsOnly, Category = "Identity")
    EItemRarity Rarity = EItemRarity::Common;

    /** 분류·상호작용 조건은 태그로 표현한다(Data.Item.Consumable 등). */
    UPROPERTY(EditDefaultsOnly, Category = "Identity")
    FGameplayTagContainer ItemTags;

    UPROPERTY(EditDefaultsOnly, Category = "Economy")
    int32 MaxStackSize = 1;

    UPROPERTY(EditDefaultsOnly, Category = "Economy")
    int32 BaseValue = 10;

    /** 무게는 인벤토리·물리 드롭 양쪽에서 쓰인다(kg). */
    UPROPERTY(EditDefaultsOnly, Category = "Economy")
    float MassKg = 1.f;

    // ---------- 표현 ----------
    /** 월드 드롭용. 200~800 삼각형 예산. */
    UPROPERTY(EditDefaultsOnly, Category = "Visual")
    TSoftObjectPtr<UStaticMesh> WorldMesh;

    UPROPERTY(EditDefaultsOnly, Category = "Visual")
    TSoftObjectPtr<UTexture2D> Icon;

    // ---------- 효과 ----------
    /** 획득 시 부여할 어빌리티(소모품·장비). */
    UPROPERTY(EditDefaultsOnly, Category = "Gameplay")
    TArray<TSoftClassPtr<UGameplayAbility>> GrantedAbilities;

    /** 즉시 적용할 효과(회복·버프). */
    UPROPERTY(EditDefaultsOnly, Category = "Gameplay")
    TArray<TSoftClassPtr<UGameplayEffect>> AppliedEffects;

    /** 이 아이템을 쓸 때 필요한 태그(예: Data.State.Dead). */
    UPROPERTY(EditDefaultsOnly, Category = "Gameplay")
    FGameplayTagContainer RequiredTags;

    /** 이 아이템이 부여하는 상호작용 태그(예: Interaction.Loot). */
    UPROPERTY(EditDefaultsOnly, Category = "Interaction")
    FGameplayTagContainer InteractionTags;

    virtual FPrimaryAssetId GetPrimaryAssetId() const override
    {
        return FPrimaryAssetId(TEXT("Item"), ItemId);
    }
};
```

`DefaultGame.ini`에 스캔 규칙을 등록한다.

```ini
[/Script/Engine.AssetManagerSettings]
+PrimaryAssetTypesToScan=(PrimaryAssetType="Item",AssetBaseClass="/Script/MyGame.ItemDefinition",bHasBlueprintClasses=False,bIsEditorOnly=False,Directories=((Path="/Game/Data/Items")),Rules=(MinChunkId=0,Priority=0,ChunkId=0))
```

이렇게 하면 `UAssetManager::Get().GetPrimaryAssetIdList(FPrimaryAssetType("Item"))`로 전체 목록을 뽑아 **검증 스크립트**(중복 `ItemId`, 아이콘 누락, 스택 0)를 돌릴 수 있다. 300개를 눈으로 검사하는 것보다 3초짜리 자동 검증이 낫다.

### 2.2 아이템 정의 스키마

| 필드 묶음 | 필드 | 왜 필요한가 |
| --- | --- | --- |
| 식별 | `ItemId`, `DisplayName`, `Rarity`, `ItemTags` | 세이브·복제·UI의 공통 키. 표시 문자열을 키로 쓰지 않는다 |
| 경제 | `MaxStackSize`, `BaseValue`, `MassKg` | 인벤토리 규칙과 드롭 물리(질량) |
| 표현 | `WorldMesh`, `Icon`, (선택) `EquipMesh` | 월드/UI/장착의 3가지 표현을 분리 |
| 효과 | `GrantedAbilities`, `AppliedEffects` | GAS 연계. 아이템이 로직을 갖지 않게 한다 |
| 조건 | `RequiredTags`, `InteractionTags` | "죽은 상태에서는 못 쓴다" 같은 규칙을 태그로 |
| 참조 | (간접) `PickupActorClass` | 드롭 액터를 아이템별로 바꿀 때 |

원칙: **아이템 데이터에 로직을 넣지 않는다.** 아이템은 "이런 효과를 준다"만 선언하고, 실행은 GAS 어빌리티가 한다. 그래야 세이브·복제·밸런싱이 한 곳에서 끝난다.

### 2.3 상호작용: 인터페이스 + 쿼리 구조

상호작용은 보통 다음 세 층으로 나눈다. 한 덩어리로 만들면 "문 열기"와 "아이템 줍기"가 서로의 코드를 침범한다.

```
[인터페이스]  IInteractableTarget — "나와 상호작용할 수 있는 것"
              · GatherInteractionOptions(Query, OutOptions)
              · CanInteract(Query) : bool
              · Interact(Query) : 실행
[쿼리]        FInteractionQuery — 누가(PlayerState) 언제/어떤 태그로
[옵션]        FInteractionOption — 표시 텍스트, 아이콘, 소요시간, 태그, 실행 함수
[매니저]      컴포넌트가 매 틱(또는 0.1초 간격) 시야 트레이스로 후보를 모아
              거리·각도·태그로 정렬해 UI에 "가장 적합한 1개"를 제시
```

Lyra의 `IInteractableTarget`이 이 구조의 레퍼런스 구현이다. 최소 구현은 다음과 같다.

```cpp
// InteractableTarget.h
#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "GameplayTagContainer.h"
#include "InteractableTarget.generated.h"

USTRUCT(BlueprintType)
struct FInteractionOption
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadWrite) FText ActionText;
    UPROPERTY(BlueprintReadWrite) FGameplayTag InteractionTag;
    UPROPERTY(BlueprintReadWrite) float HoldDuration = 0.f;   // 0이면 즉시
    UPROPERTY(BlueprintReadWrite) int32 Priority = 0;
    UPROPERTY(BlueprintReadWrite) TWeakObjectPtr<AActor> Target;
};

UINTERFACE(MinimalAPI, BlueprintType)
class UInteractableTarget : public UInterface
{
    GENERATED_BODY()
};

class MYGAME_API IInteractableTarget
{
    GENERATED_BODY()

public:
    /** 이 대상이 지금 제시할 수 있는 상호작용 목록을 채운다. */
    virtual void GatherInteractionOptions(const FInteractionQuery& Query, TArray<FInteractionOption>& OutOptions) = 0;
};
```

트레이스를 매 프레임 쏘지 않는다. 0.1초 간격(초당 10회)이면 충분하고, 플레이어 1명당 레이캐스트 10회/초는 예산 안에 들어간다. 후보가 바뀔 때만 UI를 갱신한다.

### 2.4 GAS 연계: 획득은 "부여", 사용은 "어빌리티"

| 사건 | GAS에서 하는 일 | 하지 말아야 할 일 |
| --- | --- | --- |
| 아이템 획득 | `ASC->GiveAbility(FGameplayAbilitySpec(...))` + `AppliedEffects` 적용 | 액터에서 직접 체력·스탯 수정 |
| 아이템 장착 | 어빌리티 spec에 `DynamicAbilityTags`·입력 태그 연결 | 장비마다 별도 액터 |
| 아이템 사용 | `Ability`가 `WaitGameplayEvent`/입력으로 트리거, 비용·쿨다운은 GE로 | 사용 조건을 if문으로 UI에만 구현 |
| 상호작용 | `SendGameplayEvent(Interaction.Open, Payload)`로 게임플레이 이벤트 발행 | 인터페이스가 직접 상태 변경 |

```cpp
// 장비 획득 시 어빌리티 부여 (서버에서만)
void UInventoryComponent::GrantItem(const UItemDefinition* Definition, int32 Count)
{
    if (!HasAuthority() || !Definition || !AbilitySystemComponent) { return; }

    for (const TSoftClassPtr<UGameplayAbility>& AbilityClass : Definition->GrantedAbilities)
    {
        UClass* Loaded = AbilityClass.LoadSynchronous();   // 인벤토리는 이미 로드된 상태를 전제
        if (!Loaded) { continue; }

        FGameplayAbilitySpec Spec(Loaded, Count, INDEX_NONE, this);
        Spec.DynamicAbilityTags.AddTag(Definition->InteractionTags.First());
        AbilitySystemComponent->GiveAbility(Spec);
    }

    for (const TSoftClassPtr<UGameplayEffect>& EffectClass : Definition->AppliedEffects)
    {
        if (UClass* Loaded = EffectClass.LoadSynchronous())
        {
            const FGameplayEffectContextHandle Context = AbilitySystemComponent->MakeEffectContext();
            AbilitySystemComponent->ApplyGameplayEffectToSelf(Loaded->GetDefaultObject<UGameplayEffect>(), 1.f, Context);
        }
    }
}
```

`LoadSynchronous`는 편하지만 **스트리밍 중인 오픈월드에서 히치를 만든다.** 실제로는 인벤토리 화면 진입 시 `RequestAsyncLoad`로 미리 받아 두고, 게임플레이 경로에서는 이미 로드된 에셋만 참조한다.

### 2.5 월드 드롭: 인스턴싱·풀링·디스폰

플레이어가 떨어뜨린 아이템, 상자에서 쏟아진 루팅, 사망 드롭은 모두 "월드 아이템"이다. 이들이 수백 개 쌓이면 개별 액터로는 감당이 안 된다.

| 규모 | 방식 | 비용 |
| --- | --- | --- |
| 1~20개(주변, 상호작용 대상) | 개별 `APickupActor` + 회전/부유 애니메이션 | 무시 가능 |
| 20~200개(전장에 흩어진 루팅) | HISM 인스턴스 + 인스턴스 인덱스↔데이터 매핑 | 드로우콜 1~3 |
| 200개 이상 / 대량 파괴 후 | HISM + 물리 없이 스냅 배치, 일정 수 이상은 오래된 것부터 소멸 | |
| 물리로 굴러다녀야 하는 소수 | 개별 액터, 10~20초 후 `bSimulatePhysics=false`로 고정 | 물리 비용 |

핵심 규칙 네 가지.

1. **디스폰은 시간이 아니라 예산 기준으로.** "5분 뒤 삭제"는 플레이어가 마을을 떠났다 돌아왔을 때 텅 빈 땅을 만든다. 월드 전체 드롭 수 상한(예: 400)을 두고, 상한 초과 시 **화면 밖 + 가장 오래된 것**부터 정리한다.
2. **회전·부유는 액터 틱이 아니라 셰이더/ISM 커스텀 데이터로.** HISM 인스턴스에 시간 기반 오프셋을 주는 머티리얼(WPO)이면 인스턴스 200개가 틱 비용 0이다.
3. **드롭 상태는 저장해야 한다.** 플레이어가 떨어뜨린 물건은 세이브 대상이다. World Partition 셀 단위로 "이 셀의 드롭 목록"만 diff로 저장한다.
4. **루팅 연출과 데이터 반영을 분리한다.** 아이템이 인벤토리에 들어간 것은 서버 결정이다. 연출은 클라이언트가 하고, 실패 시 되돌린다.

```cpp
// PickupActor.cpp (발췌) — 획득 요청은 서버가 판정한다
void APickupActor::Interact(const FInteractionQuery& Query)
{
    if (!HasAuthority()) { return; }   // 클라이언트는 요청만 보낸다

    const UItemDefinition* Definition = ItemDefinition.LoadSynchronous();
    if (!Definition || !Query.Interactor) { return; }

    UInventoryComponent* Inventory = Query.Interactor->FindComponentByClass<UInventoryComponent>();
    if (!Inventory || !Inventory->TryAddItem(Definition, StackCount))
    {
        return;   // 인벤토리 가득 참 등 — 액터는 그대로 남는다
    }

    // 획득 성공 시에만 제거하고, 연출은 클라이언트에서 재생한다.
    Multicast_PlayPickupFX(GetActorLocation());
    Destroy();
}
```

### 2.6 스트리밍과 상태

오픈월드 아이템은 "월드에 존재하는 것"과 "아직 로드되지 않은 것"이 섞인다. 규칙은 다음 세 줄이다.

- **참조는 소프트로.** 아이템 정의·메시·아이콘은 `TSoftObjectPtr`. 액터가 하드 참조하면 셀 로드맵이 무너진다.
- **상태는 ID로.** "상자 3번이 열렸다"를 액터 포인터로 저장하지 않고 `FPrimaryAssetId`/`FGuid` + 불리언으로 저장한다. 액터는 다시 스폰될 수 있다.
- **복원은 스폰 후.** `APickupActor::PostInitializeComponents`나 World Partition의 `OnLoaded` 이후에 상태를 적용한다. 스폰 전에 적용하면 덮어써진다.

```cpp
// 월드 상태 저장: 액터 인스턴스가 아니라 안정 ID로
USTRUCT()
struct FWorldItemState
{
    GENERATED_BODY()

    UPROPERTY() FGuid PersistentId;          // 액터 배치 시 부여한 고유 ID
    UPROPERTY() FPrimaryAssetId ItemId;
    UPROPERTY() int32 Count = 0;
    UPROPERTY() FVector Location = FVector::ZeroVector;
};

USTRUCT()
struct FCellItemStates
{
    GENERATED_BODY()

    UPROPERTY() FIntPoint CellCoord;
    UPROPERTY() TArray<FWorldItemState> Consumed;   // 더 이상 없는 것만 저장(diff)
};
```

---

## 3. 건축물: 모듈러 킷과 실내·외 렌더링

### 3.1 모듈러 설계 원칙

건물을 "한 덩어리 메시"로 만들면 ① 수정 비용이 기하급수로 오르고 ② 실내를 넣을 수 없고 ③ 창문 하나 바꾸려면 리임포트다. 그래서 건축은 **킷(부품 세트) + 조립 규칙**으로 만든다.

```
킷 = 그리드에 물리적으로 맞물리는 부품 집합
     · 모든 부품은 100 cm 그리드의 배수 크기
     · 벽 두께(모듈 두께)는 킷 전체에서 동일: 실내 15 cm, 실외 30 cm
     · 벽/바닥/지붕은 "같은 축"을 공유한다: 벽 상단 = 층고, 하단 = 바닥 레벨
     · 문·창은 "벽을 대체하는 부품"이 아니라 "벽의 개구부를 채우는 부품"
```

조립 규칙 없이 부품만 만든 킷은 반드시 실패한다. 킷을 만들기 전에 **한 평면도에서 시작해 벽 4개짜리 방을 조립해 보고**, 그 과정에서 필요한 부품 목록을 뽑는다. 이 "1실 검증"을 통과하지 못한 킷은 200개 부품이 되어도 쓸 수 없다.

### 3.2 킷 분해 구조

| 분류 | 부품 | 그리드 | 비고 |
| --- | --- | --- | --- |
| 벽 | `SM_Wall_4m`, `Wall_2m`, `Wall_1m` | 100 cm 배수, 높이 300/350 cm | 두께 15(내벽)/30(외벽) |
| 코너 | `SM_WallCorner_In`, `_Out` | 100 cm | 안/밖 코너는 별도 부품(겹침 방지) |
| 개구부 | `SM_DoorFrame_1m`, `WindowFrame_1m/2m` | 100 cm | 벽 대체형이 아니라 삽입형 |
| 개구부 채움 | `SM_Door_Single`, `_Double`, `SM_Window_*` | — | 열림 상태별 메시 또는 본 |
| 바닥 | `SM_Floor_4x4`, `Floor_2x4` | 200/400 cm | 실내/실외 노출면 분리 |
| 천장 | `SM_Ceiling_4x4`, `SM_Beam_4m` | 400 cm | 보(Beam)는 노출 천장용 |
| 지붕 | `SM_Roof_Slope_30`, `_45`, `SM_Ridge`, `SM_Eave` | 경사별 | 경사·처마·용마루 3종 |
| 계단 | `SM_Stairs_3m`, `SM_Stairs_4m`, `SM_Handrail_*` | 층고 기준 | 7.7절 계단 공식 참조 |
| 난간·발코니 | `SM_Railing_2m`, `SM_Balcony_2x1` | 200 cm | 높이 110 cm(게임 기준) |
| 장식 | `SM_Cornice_2m`, `SM_Pilaster_3m`, `SM_Louver_1m`, `SM_Plinth_2m` | 200 cm | 파사드 디테일은 별도 킷 |
| 실내 | `SM_Interior_Doorframe`, `SM_Baseboard`, `SM_Trim_*` | 100 cm | 실내는 별도 킷(두께 다름) |

부품 명명에 **크기와 두께를 넣는다.** `SM_Wall_4m_T15`처럼. 조립하는 사람이 메시를 열어보지 않고도 고를 수 있어야 한다.

### 3.3 벽 두께와 라이팅: 루멘 누광의 90 %는 두께에서 온다

Lumen(그리고 베이크 라이트맵)은 **얇은 벽을 통과해 빛을 새게 한다.** 이유는 두 가지다.

1. **거리 필드(Distance Field) 해상도.** 메시의 거리 필드는 복셀화된다. 벽 두께가 복셀 크기(대략 수 cm)보다 얇으면 벽이 "구멍 난 판"으로 표현되어 간접광이 통과한다.
2. **서피스 캐시(Surface Cache) 카드.** Lumen은 메시를 카드로 근사해 GI를 계산한다. 두께가 없으면 카드가 실내 외벽을 구분하지 못한다.

실무 규칙:

| 항목 | 최소 | 권장 | 비고 |
| --- | --- | --- | --- |
| 실내 격벽 두께 | 10 cm | 15 cm | 10 cm 미만은 실험적. 누광이 보이면 즉시 두껍게 |
| 외벽 두께 | 20 cm | 30~40 cm | 단열·구조 두께와 일치해 자연스럽다 |
| 바닥 슬래브 | 15 cm | 20~30 cm | 아래층 천장과 공유 |
| 문 개구부 주변 | 벽 두께 유지 | | 프레임이 벽을 대체하지 않게(겹침 = 누광) |
| 이중벽(실내+실외) | 두 메시 겹침 금지 | 한 메시로 | 겹치면 거리 필드가 깨진다 |

메시 쪽 설정 체크리스트:

- **`Generate Mesh Distance Fields`** 프로젝트 설정이 켜져 있는지(기본 켜짐), 메시별 `Distance Field Resolution Scale`은 벽 부품에서 1.0 이상. 얇은 장식은 오히려 낮춘다.
- **양면 메시(`Two Sided`)는 피한다.** 양면 메시는 거리 필드가 "종이"로 생성되어 누광의 주범이 된다. 실내에서 보이는 면이 필요하면 **면을 뒤집은 별도 메시**(내벽 부품)를 쓴다.
- **`Affect Distance Field Lighting`** 은 큰 구조물만 켠다. 소품·데칼·난간까지 켜면 거리 필드 빌드 시간과 메모리가 폭증한다.
- **실내 조명은 Area Light로.** 창밖 태양광만으로는 실내 GI가 부족하다. 창 안쪽에 Rect Light(창 크기와 일치)를 두고 `Source Radius`를 창틀에 맞춘다. 실제 태양광이 창을 통과하는 것처럼 보이게 하는 가장 값싼 방법이다.
- **VSM(Virtual Shadow Map) 해상도 한계.** 작은 방에 점광원 20개를 넣으면 VSM 페이지가 부족해 그림자가 사라지거나 새어 들어온다. 방당 동적 광원을 3~5개로 제한하고 나머지는 이미시브/디칼로 대체한다.

### 3.4 실내 렌더링: "오클루전 포탈"은 UE에 없다

Source 엔진의 portal이나 Unity의 Umbra처럼 **방 단위로 가시성을 잘라내는 오클루전 포탈 시스템은 UE5에 없다.** UE5의 기본 가시성 컬링은 프러스텀 + HZB(깊이 버퍼 기반) 오클루전 + Nanite 소프트웨어 래스터이며, 이는 "화면에 안 보이는 것"을 자동으로 걸러 준다. 즉 방문 너머는 이미 그려지지 않는다. 문제는 **보이지만 비용이 큰 것**(문 너머로 보이는 실내 전체)과 **그려지지만 필요 없는 것**(멀리 있는 방의 라이트·오디오·애니메이션)이다.

그래서 UE에서 실제로 쓰는 대체 수단은 다음 네 가지다.

| 목적 | 수단 | 특징 |
| --- | --- | --- |
| 그리지 않기 | Nanite + HZB 오클루전, `Cull Distance Volume`, 프리미티브 `Max Draw Distance` | 자동. 문 너머 실내 전체가 보이면 소용없다 |
| 로드하지 않기 | World Partition 셀 분할, `Level Instance`(건물 단위), `Data Layer`(층·실 단위) | 건물 하나를 Level Instance로 묶으면 실내 전체가 한 단위로 로드된다 |
| 계산하지 않기 | 방 단위 라이트 끄기(오버랩 볼륨 + `SetVisibility`), 오디오 존 | 실내 라이트가 5개 넘으면 방별 토글이 정답 |
| 미리 계산하기 | `Precomputed Visibility Volume`(모바일·정적 전용), HLOD | 정적 씬에서만. 동적 오브젝트에는 무효 |

실무 패턴: **건물 = Level Instance 1개, 층 = Data Layer, 방 = 라이트 그룹.** 플레이어가 문을 열면 그 방의 라이트·오디오·NPC 틱을 켜고, 나가면 1~2초 뒤 끈다. 이 "수면(sleep)" 관리가 오픈월드 실내의 실제 최적화다.

```cpp
// 방 단위 활성/비활성 (레벨에 배치한 ARoomVolume이 관리)
void ARoomVolume::SetRoomActive(bool bActive)
{
    for (const TSoftObjectPtr<AActor>& ActorPtr : ManagedActors)
    {
        if (AActor* Actor = ActorPtr.Get())
        {
            Actor->SetActorTickEnabled(bActive);
            Actor->SetActorHiddenInGame(!bActive);
        }
    }

    for (ULightComponent* Light : ManagedLights)
    {
        if (Light)
        {
            Light->SetVisibility(bActive);
            Light->SetComponentTickEnabled(bActive);
        }
    }
}
```

주의: 숨긴 액터도 **콜리전은 남는다.** 플레이어가 벽을 통과하지 않게 콜리전은 유지하고, 시각·틱·오디오만 끈다.

### 3.5 실내·외 최적화 표

| 항목 | 실외 | 실내 |
| --- | --- | --- |
| 지오메트리 | Nanite, HLOD 프록시 | Nanite(세부 몰딩), 단순 콜리전 |
| 라이팅 | Directional + SkyLight + Lumen Far Field | Rect Light(창) + 소수 점광 + 이미시브 |
| 반사 | Lumen Reflections(거칠기 기반) | 반사 캡처(방 단위) 또는 Lumen |
| 안개 | Volumetric Fog(원경) | 얇은 볼류메트릭 또는 없음 |
| 텍스처 | RVT + 타일링 | 트림 시트 + 디칼 |
| 컬링 | HLOD + 거리 | Level Instance + 라이트 토글 |
| 오디오 | 3D 감쇠 | 리버브 존 + 차폐(occlusion) |

실내는 "폴리곤이 적은 대신 라이트가 많은" 환경이다. 그래서 실내 예산은 삼각형이 아니라 **광원 수·반투명 면적·오버드로우**로 잡는다.

### 3.6 머티리얼: 단일 마스터 + 트림 시트 + 버텍스 블렌드

건축 모듈은 수백 개가 화면에 동시에 뜬다. 모듈마다 머티리얼 인스턴스가 다르면 머티리얼 스위치 수가 폭발하고, Nanite는 머티리얼당 별도 패스로 그려져 비용이 커진다. 해법은 **머티리얼 1~2개로 모든 모듈을 덮는 것**이다.

1. **트림 시트(Trim Sheet)**: 2048×2048 한 장에 벽·몰딩·창틀·난간 프로파일을 가로 띠로 배치한다. 모듈은 UV를 그 띠에 매핑한다. 텍스처 1장으로 200개 모듈을 덮는다.
2. **틸링 PBR**: 벽면의 기본 벽돌·콘크리트는 타일링 텍스처 + 매크로 배리에이션(대형 노이즈로 색·거칠기 변화)으로 반복감을 없앤다.
3. **버텍스 컬러 블렌딩**: 버텍스 색 R=이끼, G=오염, B=균열 마스크로 3가지 레이어를 블렌드한다. 같은 메시로 "새 건물/오래된 건물/폐허"를 만든다.
4. **월드 정렬 디테일**: 트라이플래너/월드 정렬 텍스처로 UV 스트레치 없이 바닥에 때·물자국.
5. **디칼**: 낙서·피·물웅덩이는 메시가 아니라 데칼. 데칼 예산(화면당 30~60개)을 정하고 초과 시 페이드.

| 기법 | 해결하는 문제 | 비용 |
| --- | --- | --- |
| 트림 시트 | 모듈 간 텍스처 통일, 머티리얼 슬롯 1개 | UV 작업 시간 |
| 틸링 + 매크로 배리에이션 | 반복 티 | 텍스처 샘플 1~2 |
| 버텍스 컬러 블렌드 | 다형성(같은 메시, 다른 상태) | 정점 1개 |
| 월드 정렬 디테일 | UV 스트레치, 대형 면의 반복 | 샘플 1~2 |
| 디칼 | 국소 디테일 | 드로우콜 + 오버드로우 |

### 3.7 건물 배치와 내부 채우기 순서

```
① 매스(massing)     건물 덩어리를 박스로 배치, 스카이라인/실루엣 확인
② 구조 그리드       기둥 간격(6~8 m)을 잡고 그리드에 벽·바닥을 스냅
③ 동선              입구 → 로비 → 주요 방의 흐름을 화살표로 검증(플레이어 시점 캡처)
④ 실내 볼륨         방 크기·문 위치·창 위치 확정. 여기서 계단을 넣고 층고 검증
⑤ 모듈 조립         킷으로 ③④를 재구성. 개구부·장식 추가
⑥ 드레싱            가구·소품·디칼. 방별 "1차 실루엣 소품 1개 + 잔여 클러터"
⑦ 라이팅            창 Rect Light → 실내 점광 → 이미시브. 방별 3~5광원 상한
⑧ 검증              플레이어 동선으로 걸어보며 캡슐·카메라·문 통과 확인
```

③과 ④를 박스로 먼저 하는 것이 핵심이다. 킷으로 바로 만들면 "계단이 층고에 안 맞는다"를 조립 후에 발견한다.

### 3.8 인게임 건축 시스템(런타임 건설)

플레이어가 게임 중에 직접 벽·바닥·계단·기둥·지붕을 세우는 시스템(러스트·팰월드·포트나이트·발하임 계열)은 **레벨 디자이너가 만드는 건축과 정반대의 제약**을 갖는다. 디자이너는 결과를 알고 배치하지만, 플레이어는 아무 데나 세우려 하고, 그 결과는 네트워크를 건너야 하며, 잘못 세운 구조는 무너져야 한다.

#### 3.8.1 네 덩어리로 나눈다

```
[정의]   UBuildPieceDefinition — 조각의 크기·메시·소켓·지지 비용 (데이터)
   │
[프리뷰] UBuildSystemComponent (클라이언트) — 트레이스 → 스냅 → 유효성 → 색
   │  Server RPC (위치·회전·정의·지지 조각)
   ▼
[권위]   ABuildManager (서버) — 재검증 → 스폰 → 지지 그래프 재계산 → 붕괴
   │  액터 스폰 복제
   ▼
[표현]   ABuildPieceActor (모든 클라이언트) — 메시·충돌, 피해·철거
```

핵심 원칙: **판정은 서버, 피드백은 클라이언트.** 클라이언트가 "초록색이니까 놓겠다"고 결정하지 않는다. 클라이언트는 서버와 **같은 검증 함수**를 로컬에서 호출해 즉각적인 색을 보여주고, 실제 설치는 서버 요청으로만 일어난다.

| 요구 | Rust/Palworld 계열 | Fortnite 계열 | 설계 결정 |
| --- | --- | --- | --- |
| 조각 크기 | 1~3 m 그리드 | 4 m 타일 | `ExtentCm` + 그리드 배수 |
| 스냅 | 소켓(정밀) + 그리드 | 그리드 + 소켓 | 소켓 우선, 그리드 폴백 |
| 안정성 | 지지 그래프(붕괴) | 없음(즉시 설치) | 지지 그래프는 선택 기능으로 |
| 자원 | 조각마다 소모 | 조각마다 소모 | 서버에서 인벤토리 검증 |
| 철거 | 부분 회수 | 즉시 | 서버 판정 + 부분 환급 |

#### 3.8.2 조각 정의와 그리드 모델

조각 정의는 **에셋**이고, 배치 규칙은 그 에셋의 숫자다. 코드에 `if (PieceType == Wall)`을 늘어놓지 않는다.

| 필드 | 의미 | 예시 |
| --- | --- | --- |
| `PieceType` | UI 분류·규칙 분기 | Foundation / Wall / Floor / Stair / Pillar / Roof |
| `ExtentCm` | 절반 크기(cm) | 4 m 벽 → (200, 10, 150) |
| `SnapSockets` | 메시 소켓 이름 | `Snap_Top`, `Snap_Bottom`, `Snap_Left`, `Snap_Right` |
| `SupportCost` | 지지 하중 | 벽 1, 바닥 2, 지붕 1 |
| `bIsRoot` | 지면에 닿는 뿌리인가 | 기초·바닥 true |
| `SupportCapacity` | 뿌리가 견디는 누적 하중 | 기초 8~12 |
| `MaxSupportGapCm` | 지지 연결 인정 거리 | 25 cm |

그리드는 **100 cm**를 표준으로 한다. 4 m 벽은 400×20×300 cm이고, 문 개구부는 100 cm 배수로 뚫는다(7.2절의 게임 스케일과 동일한 그리드). 플레이어가 100 cm 그리드에 놓으면 벽과 바닥이 항상 맞물린다.

#### 3.8.3 고스트 프리뷰와 유효성 검사

프리뷰는 반투명 "홀로그램" 메시다. 색만 바꾸면 되므로 원본 메시를 그대로 쓰고, 머티리얼만 반투명 프리뷰 머티리얼로 교체한다.

```
매 틱(또는 30~60 Hz로 제한)
  ① 카메라에서 전방 600 cm 라인 트레이스(ECC_Visibility)
  ② 히트 → 스냅 트랜스폼 계산(3.8.4)
  ③ 사거리 검사(캐릭터 → 조각 최원점)
  ④ 겹침 검사: 조각 크기의 98 % 박스로 OverlapBlockingTest
       · 대상: WorldStatic / WorldDynamic / Pawn
       · 제외: 건축 조각 전용 채널(BuildPiece), 프리뷰 자신, 플레이어
  ⑤ 지지 검사: 아래쪽 조각/지면이 MaxSupportGapCm 안에 있는가
  ⑥ 색 적용: Valid → 초록, 실패 → 빨강(+ 아이콘/사유)
```

겹침 검사에서 **건축 조각을 제외하는 전용 채널**이 핵심이다. 조각이 모두 WorldStatic이면 이웃 벽과 맞대는 순간 겹침 판정이 나서 아무것도 못 쌓는다. 프로젝트 설정에서 `BuildPiece` 오브젝트 채널을 만들고 조각의 `SetCollisionObjectType`을 그것으로 지정하며, 검증 쿼리에는 그 채널을 넣지 않는다.

```cpp
// 크기를 98 %로 줄여 "맞댐"은 허용하고 "관통"만 막는다.
const FCollisionShape Shape = FCollisionShape::MakeBox(Definition->ExtentCm * 0.98f);

FCollisionObjectQueryParams ObjectParams;
ObjectParams.AddObjectTypesToQuery(ECC_WorldStatic);
ObjectParams.AddObjectTypesToQuery(ECC_WorldDynamic);
ObjectParams.AddObjectTypesToQuery(ECC_Pawn);
// ECC_GameTraceChannel1(BuildPiece)은 의도적으로 제외한다.

const bool bBlocked = World->OverlapBlockingTestWithParams(Location, Rotation, Shape, QueryParams, ObjectParams);
```

프리뷰 갱신 비용을 줄이는 요령:

| 기법 | 값 | 이유 |
| --- | --- | --- |
| 갱신 주기 제한 | 30~60 Hz (`TickInterval` 또는 누적 시간) | 매 프레임 트레이스는 낭비 |
| 트레이스 ignore 목록 | 프리뷰 메시, 플레이어, 소유 차량 | 자기 자신에 걸리면 항상 무효 |
| 표시 억제 | 유효하지 않으면 프리뷰 숨김(또는 30 % 알파) | "무효인데 보임"이 혼란을 만든다 |
| 사유 표시 | `EPlacementResult` → UI 문구/아이콘 | 플레이어가 무엇이 문제인지 안다 |
| 프리뷰 메시 | 충돌 끔, 그림자 끔, 데칼 수신 끔 | 렌더 비용 최소 |

#### 3.8.4 스냅: 소켓 우선, 그리드 폴백

스냅이 어긋나면 조각 사이에 틈이 생기고, 그 틈으로 빛이 샌다(3.9.5). 두 단계로 처리한다.

**① 소켓 스냅.** 조각 메시에 소켓을 대칭으로 박아 둔다(벽: `Snap_Top`/`Snap_Bottom`/`Snap_Left`/`Snap_Right`). 새 조각의 소켓을 기존 조각의 **반대편 소켓**에 일치시킨다.

```
목표: T_new * (내 소켓 로컬 트랜스폼) = (상대 소켓 월드 트랜스폼)
∴    T_new = OtherSocketWorld * Inverse(OwnSocketLocal)
```

여러 소켓 쌍 중에서는 **커서에 가장 가까운 결과**를 고른다. 이렇게 하면 벽 위에 벽을 쌓을지, 옆에 붙일지를 플레이어가 커서 위치만으로 결정한다.

**② 그리드 폴백.** 소켓이 없거나 상대가 건축 조각이 아니면 히트 지점을 그리드로 내린다.

```
Location = GridSnap(ImpactPoint, 100 cm)
Rotation.yaw = GridSnap(Pawn.ControlRotation.Yaw, 90°)
```

주의할 점:

| 상황 | 문제 | 대응 |
| --- | --- | --- |
| 경사면 | 조각이 기울어 벽이 쓰러진다 | up 벡터와 지면의 각이 25° 넘으면 배치 금지 |
| 소켓 회전 | 벽이 안쪽/바깥쪽을 향한다 | 소켓에 회전을 포함(로컬 트랜스폼 전체 사용) |
| 계단 | 바닥에 붙지 않고 뜬다 | 계단은 전용 소켓 또는 하단 피벗 고정 |
| 45° 배치 | 지그재그 벽이 필요 | yaw 스냅 단계에 45° 옵션(별도 부품) |
| 조각 크기 불일치 | 3 m 벽 + 4 m 바닥이 안 맞는다 | 모든 정의의 ExtentCm를 그리드 배수로 강제 |

```cpp
// 소켓 쌍 중 커서에 가장 가까운 배치를 고른다.
const FTransform Candidate = OtherSocketWorld * OwnSocketLocal.Inverse();
const float Distance = FVector::Dist(Candidate.GetLocation(), Hit.ImpactPoint);
if (Distance < BestDistance) { BestDistance = Distance; OutTransform = Candidate; }
```

#### 3.8.5 구조 안정성: 지지 그래프

플레이어가 기둥을 부수면 위층이 무너지는 것이 이 시스템의 재미다. 계산은 **그래프 탐색 + 하중 전파** 두 단계다.

```
① 연결성 BFS
   뿌리(지면에 닿은 기초)에서 시작해, 경계가 Gap 이내로 접한 조각을 이웃으로 본다.
   도달 불가능한 조각 = 지지 없음 → 붕괴 후보

② 하중 전파
   BFS 트리의 부모(지지 방향)를 따라 잎 → 뿌리로 SupportCost를 누적한다.
   뿌리의 누적 하중 > SupportCapacity → 그 트리 붕괴

③ 연쇄
   붕괴 후 다시 ①부터. 최대 4회(안전 상한)까지 반복한다.
```

| 파라미터 | 의미 | 시작값 | 조정 감각 |
| --- | --- | --- | --- |
| `SupportLinkGapCm` | 이웃 인정 거리 | 25 | 늘리면 너그러워진다(틈도 지지) |
| `SupportCost` | 조각 무게 | 벽 1, 바닥 2 | 높이면 얇게 못 쌓는다 |
| `SupportCapacity` | 뿌리 허용 하중 | 8~12 | 12면 12칸 높이까지 |
| `MaxIntegrityPasses` | 연쇄 붕괴 상한 | 4 | 무한 루프 방지 |
| 이웃 Bounds 확장 | 접촉 판정 | Gap만큼 확장 후 교집합 | 조각 경계가 조금 겹쳐도 연결로 본다 |

비용: 조각 N개에 대해 O(N²) 이웃 검사다. N ≤ 2,000이면 서버에서 한 번 계산에 수 ms이고, 배치·철거 시에만 돌므로 문제없다. 10,000개를 넘기면 조각을 셀(10 m)로 나눠 공간 해시로 이웃을 찾는다.

```cpp
// 지지되지 않는 조각을 추린다(발췌).
TSet<ABuildPieceActor*> Reachable;
TArray<ABuildPieceActor*> Queue;

for (ABuildPieceActor* Piece : Pieces)
{
    if (Piece && Piece->Definition && Piece->Definition->bIsRoot)
    {
        Reachable.Add(Piece);
        Queue.Add(Piece);
    }
}

for (int32 Head = 0; Head < Queue.Num(); ++Head)
{
    for (ABuildPieceActor* Candidate : Pieces)
    {
        if (!Candidate || Reachable.Contains(Candidate)) { continue; }
        if (ArePiecesConnected(Queue[Head], Candidate))
        {
            Reachable.Add(Candidate);
            Queue.Add(Candidate);
            Parent.Add(Candidate, Queue[Head]);   // 하중 전파용 부모
        }
    }
}
```

붕괴 연출은 "조각을 지우는 것"이 아니라 **"물리 액터로 바꿔 떨어뜨리는 것"**이다. 서버가 조각을 제거하고, 모든 클라이언트에 붕괴 위치·개수를 Multicast해 파편(나이아가라·물리 프록시)을 스폰한다. 파편은 3~5초 뒤 정리한다.

#### 3.8.6 서버 권위와 멀티플레이 흐름

```
[클라] 프리뷰 초록 → TryPlace()
        │ ① Server_RequestPlace(Definition, Location, Rotation, SupportId)
        ▼
[서버] ② 정의 유효성(스캔된 데이터인가)
       ③ 사거리 재검증(캐디: 클라 위치 + 여유 100 cm)
       ④ 겹침·지지 재검증(클라와 같은 함수, 서버 월드 기준)
       ⑤ 자원 검증(인벤토리·재화) — 실패 시 사유 반환
       ⑥ 스폰 → 지지 그래프 재계산 → 붕괴 처리
        │ ⑦ 실패 시 Client_PlacementRejected(사유)
        ▼
[모두] 액터 스폰 복제로 조각이 나타난다(별도 Multicast 불필요)
```

| 검증 항목 | 왜 서버에서 다시 하는가 |
| --- | --- |
| 사거리 | 클라이언트 좌표 스푸핑 |
| 정의 유효성 | 임의 클래스/에셋 주입 |
| 겹침·지지 | 클라이언트가 검증을 건너뛸 수 있다 |
| 자원 | 무한 건축(치트) |
| 빈도 | 초당 요청 수 제한(예: 10회) |

복제 방식은 두 가지 중에서 고른다.

| 방식 | 구현 | 장점 | 단점 |
| --- | --- | --- | --- |
| **액터 스폰** | 조각마다 `ABuildPieceActor` | 단순, 충돌·피해·철거가 자연스럽다 | 조각 1,000개 = 액터 1,000개(틱·네트워크 오버헤드) |
| **FastArraySerializer** | `TArray<FBuildPieceRecord>` + `FFastArraySerializer`, 렌더는 HISM | 조각 수만 개도 가능, 대역폭 최소 | 충돌·철거·개별 피해를 직접 구현 |

플레이어당 300~800조각 규모(러스트식 기지)면 액터 방식이 유지보수에 유리하다. 수만 개(도시 전체 건설)라면 FastArray + HISM으로 간다. 저장은 `FBuildPieceRecord`(안정 GUID + 정의 ID + 트랜스폼)로 남기고, 로드 시 서버가 순서대로 재스폰한다.

#### 3.8.7 예제 코드

| 파일 | 내용 |
| --- | --- |
| [`examples/unreal_cpp_building/BuildingTypes.h`](../examples/unreal_cpp_building/BuildingTypes.h) | `EBuildPieceType`, `EPlacementResult`, `UBuildPieceDefinition`, `FBuildPieceRecord`(NetSerialize), 그리드 스냅 도우미 |
| [`examples/unreal_cpp_building/BuildSystemComponent.h`](../examples/unreal_cpp_building/BuildSystemComponent.h) · [`.cpp`](../examples/unreal_cpp_building/BuildSystemComponent.cpp) | 고스트 프리뷰, 소켓/그리드 스냅, 로컬 검증, 서버 RPC, 거부 통지 |
| [`examples/unreal_cpp_building/BuildManager.h`](../examples/unreal_cpp_building/BuildManager.h) · [`.cpp`](../examples/unreal_cpp_building/BuildManager.cpp) | 조각 액터, 서버 검증, 스폰·철거, 지지 그래프 BFS·하중 전파·연쇄 붕괴 |

#### 3.8.8 인게임 건축에서 자주 터지는 것

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 벽끼리 안 붙는다 | 겹침 검사에서 건축 조각이 서로를 막는다 | `BuildPiece` 채널 분리, 쿼리에서 제외 |
| 초록인데 설치가 안 된다 | 클라·서버 검증 불일치(월드 상태 차이) | 같은 함수 사용, 실패 사유를 UI에 표시 |
| 설치한 조각이 클라이언트에서 안 보인다 | 서버에서 메시를 할당하고 `OnRep` 미구현 | `ReplicatedUsing = OnRep_Definition` |
| 조각이 두 번 생긴다 | 클라 예측 스폰 + 서버 스폰 중복 | 서버 스폰만 사용하거나 예측 조각에 서버 ID 매칭 |
| 계단이 바닥을 뚫는다 | 피벗이 중심 | 계단 피벗을 하단 전면으로 |
| 기둥 하나 부수면 전부 무너진다 | 연결 거리(Gap)가 너무 작다 | `MaxSupportGapCm` 상향(25→40) |
| 붕괴가 프레임을 끊는다 | 붕괴 계산을 매 틱 | 배치·철거 시에만, 연쇄 4회 상한 |
| 재접속 후 구조가 남지 않는다 | 레코드 저장 없음 | GUID 기반 `FBuildPieceRecord` 저장·복원 |
| 조각 1,000개에서 틱이 폭증 | 액터가 모두 틱 | 조각 액터 `PrimaryActorTick.bCanEverTick = false` |

---

### 3.9 건물 디테일 표현 기법

같은 폴리곤 예산으로 건물을 "비싸 보이게" 만드는 것은 지오메트리를 늘리는 일이 아니라 **정보를 겹쳐 쌓는 일**이다. 아래 다섯 기법은 서로 대체가 아니라 **층**이다. 트림 시트가 형태를, 버텍스 컬러가 상태를, 데칼이 시간을, 패럴랙스가 실내를, 빛샘 방지가 완성도를 만든다.

```
[형태]  트림 시트 + 가중치 노멀        → 면마다 하이라이트, 폴리곤 추가 없음
[상태]  버텍스 컬러 다층 블렌드        → 벽돌 노출·회반죽·이끼를 한 메시에서
[시간]  DBuffer 데칼 + RVT             → 균열·물때·그을음·이끼를 런타임에
[실내]  윈도우 인테리어 패럴랙스       → 창문마다 방이 있는 것처럼
[완성]  루멘 빛샘 방지 규칙           → 두께·오버랩·거리 필드
```

#### 3.9.1 트림 시트 + 가중치 노멀: 폴리곤 0 증가로 모서리를 살린다

**트림 시트(Trim Sheet)** 는 몰딩·창틀·기둥 프로파일을 한 장의 텍스처에 가로 띠로 담고, 모듈은 그 띠에 UV를 맞춰 쓰는 방식이다.

| 단계 | 내용 | 수치 |
| --- | --- | --- |
| ① 프로파일 모델링 | 하이폴리로 몰딩·베벨을 만든다 | 챔퍼 5~10 mm |
| ② 노멀/AO 베이킹 | 평면에 베이킹(베벨이 노멀에 기록된다) | 2,048², 16 bit |
| ③ 트림 시트 배치 | 세로로 8~12개 띠, 띠당 170~256 px | 텍셀 512 px/m |
| ④ UV 매핑 | 모듈의 각 면을 띠에 맞춘다 | 띠 경계 ±2 px 마진 |
| ⑤ 머티리얼 | 마스터 1개 + 파라미터(색·거칠기) | 슬롯 1개 |

**가중치 노멀(Weighted Normals)** 은 하이폴리 없이 "면마다 각진 하이라이트"를 만드는 기법이다. 정점 노멀을 면적 가중 평균으로 다시 계산하면, 큰 면이 작은 베벨 면을 누르면서 모서리에 날카로운 하이라이트가 생긴다. 로우폴리 큐브가 하이폴리 베벨처럼 보인다.

| 도구 | 명령/기능 | 결과 |
| --- | --- | --- |
| 블렌더 | Weighted Normal 모디파이어(Keep Sharp, Weight 50) | 면적 가중 노멀 |
| 3ds Max | Weighted Normal 모디파이어 | 동일 |
| 마야 | Smooth by Angle + 커스텀 노멀 | 하드 에지 유지 |
| 언리얼(임포트) | 노멀 임포트 유지, `Recompute Normals` 끔 | DCC 노멀 보존 |

주의: 가중치 노멀은 **스무딩 그룹/하드 에지 정보**에 의존한다. 임포트 후 노멀을 재계산하면 결과가 사라진다. 또 하나: UV가 겹치는 면(같은 띠를 공유)에서 노멀을 공유하면 하이라이트가 이어져 보인다 — 의도한 경우도 있고 아닌 경우도 있으니 3분할(박스 매핑)로 분리한다.

#### 3.9.2 DBuffer 데칼: 지오메트리 없이 시간을 그린다

데칼은 쿼드 하나로 표면에 텍스처를 투영한다. UE5의 **DBuffer 데칼**은 베이스 컬러·노멀·거칠기를 GBuffer 앞단에서 직접 수정하므로, 라이팅 이후에 덧그리는 일반 데칼보다 자연스럽다(빛을 받는다).

| 데칼 종류 | 블렌드 | 용도 | 비용 |
| --- | --- | --- | --- |
| DBuffer (BaseColor/Normal/Roughness) | 표면 수정 | 균열·물때·그을음·이끼 | 중(GBuffer 패스 추가) |
| 일반 데칼(Translucent) | 알파 블렌드 | 유리 깨짐·피·낙서 | 낮음 |
| 스태틱 메시 데칼 | 메시에 투영 | 차량·소품 | 낮음 |

실무 규칙:

- **데칼 예산**: 화면당 30~60개. 초과 시 `FadeScreenSize`로 자연 소멸시킨다.
- **각도**: 벽 데칼은 벽 노멀 기준으로 5~15° 기울여 투영해 "번진" 느낌을 만든다.
- **RVT 블렌딩**: 먼 거리의 데칼은 런타임 가상 텍스처(RVT)에 구워 두고, 근접 시에만 실제 데칼을 켠다. 오픈월드에서 데칼 수를 거리와 무관하게 유지하는 방법이다.
- **이끼·물때**: 아래에서 위로 갈수록 옅어지는 그라디언트를 데칼에 넣거나, 버텍스 컬러 B채널(3.9.3)과 조합한다.

```cpp
// 데칼 스폰(표면 노멀에 정렬). 방향을 틀면 투영이 기울어 자연스러워진다.
void AMyBuildingDetail::SpawnStain(const FVector& Location, const FVector& Normal, UMaterialInterface* DecalMaterial)
{
    if (!DecalMaterial || !GetWorld()) { return; }

    const FRotator AlignToNormal = FRotationMatrix::MakeFromZ(Normal).Rotator();
    const FRotator RandomTilt(0.f, FMath::FRandRange(0.f, 360.f), FMath::FRandRange(-10.f, 10.f));

    UGameplayStatics::SpawnDecalAtLocation(
        GetWorld(), DecalMaterial, FVector(120.f, 120.f, 40.f), Location + Normal * 2.f, AlignToNormal + RandomTilt);
}
```

#### 3.9.3 버텍스 컬러 다층 블렌드: 한 메시로 세 가지 상태

회반죽이 벗겨져 벽돌이 드러나고, 아래쪽에 이끼가 끼고, 모서리에 오염이 앉은 벽은 메시를 세 개 만들지 않는다. **정점 색을 마스크로** 쓰면 하나의 메시로 표현된다.

| 채널 | 마스크 | 표현 |
| --- | --- | --- |
| R | 벽돌 노출 | 회반죽이 벗겨진 자리 |
| G | 오염·물때 | 아래·모서리의 검은 때 |
| B | 이끼·풀 | 습한 쪽의 녹색 |
| A | (선택) 파손도 | 먼지·균열 강도 |

머티리얼 구성(노드 흐름):

```
VertexColor(R/G/B) → Lerp × 3
   Base: 회반죽 텍스처(틸링 2 m)
   × (1 - R) + 벽돌 텍스처(틸링 1 m, UV 스케일 다르게) × R
   × (1 - G) + 오염 텍스처(월드 정렬, 4 m) × G
   × (1 - B) + 이끼 텍스처(월드 정렬, 2 m, 노멀 플립) × B
→ BaseColor / Roughness / Normal(각 레이어 노멀 블렌드)
```

주의 사항:

| 문제 | 원인 | 대응 |
| --- | --- | --- |
| 마스크 경계가 뭉개진다 | 정점 밀도 부족(4 m 벽에 정점 8개) | 벽 모듈을 1 m 단위로 분할하거나, 경계 부분만 세분화(테셀레이션) |
| 경계가 계단처럼 보인다 | 정점 보간 | 경계를 노이즈로 흔들거나 데칼(3.9.2)로 덮는다 |
| 색이 탁해진다 | 세 레이어의 거칠기·노멀을 단순 합성 | 레이어별 노멀·거칠기를 각각 블렌드 |
| 메모리 증가 | 마스크만으로는 텍스처가 늘지 않지만 레이어 텍스처가 늘어난다 | 2K 1장에 레이어 4개를 채널 패킹 |

버텍스 페인팅은 DCC에서 하거나 언리얼의 `Mesh Paint` 모드에서 한다. 반복 사용되는 모듈은 **변형 3종(새것/중간/폐허)** 을 만들어 두고 랜덤 배치하는 것이 손으로 칠하는 것보다 빠르다.

#### 3.9.4 윈도우 인테리어 패럴랙스: 창문마다 방을 만든다

건물 외벽의 창문 수십 개에 실내를 모델링하는 것은 불가능하다. **패럴랙스 오클루전 매핑(Interior Mapping)** 은 창문 셰이더 안에서 "방의 큐브맵"을 시선에 따라 이동시켜 입체감을 만든다. 시선이 기울면 방 안의 가구가 시차를 두고 움직이므로, 실제로 방이 있는 것처럼 보인다.

```
[제작]
① 방 프리셋 3~6종을 별도 레벨에 만든다(책상·침대·조명·커튼)
② 방 중심에서 6면 큐브맵 캡처(SceneCaptureCube) → 텍스처 6장 또는 큐브맵 1장
③ 창문 머티리얼: 창 유리 영역에만 패럴랙스 셰이더
   - 픽셀의 로컬 UV → 창 깊이(예: 300 cm)만큼 광선을 전진
   - 전진한 위치의 큐브맵 UVW 샘플 → 실내 이미지
   - 창틀·커튼은 별도 레이어(알파)
④ 방 프리셋별 파라미터(깊이·밝기·색온도)를 MID로 지정
```

| 항목 | 값/규칙 | 이유 |
| --- | --- | --- |
| 창 깊이 | 200~400 cm | 얕으면 벽지처럼, 깊으면 늘어져 보인다 |
| 큐브맵 해상도 | 512~1,024 | 창문은 화면에서 작다 |
| 방 프리셋 수 | 3~6 | 많으면 메모리·관리 비용 |
| 각도 한계 | 시선 60° 이상 기울면 왜곡 | 창틀 안쪽으로 마스크해 가린다 |
| 야간 | 방 조명을 켠 큐브맵 + 발광 | 밤에 창문이 사는 느낌 |
| 비용 | 창 1개 ≈ 반투명 1장 | 창문 많은 도시는 LOD로 원거리 단순화 |

한계: 문이 열리거나 플레이어가 들어갈 수 있는 건물에는 쓸 수 없다. **배경 건물 전용**이며, 플레이 가능한 건물은 실제 실내를 만들어야 한다. 이 구분(배경용/플레이용)을 에셋 명명(`BG_`/`PL_`)으로 나누는 것이 좋다.

#### 3.9.5 루멘 인테리어 빛샘 방지: 두께와 오버랩

Lumen은 거리 필드·서피스 캐시로 간접광을 계산하므로, **얇은 벽과 틈은 빛이 통과한다.** 3.3절의 기본 규칙에 인게임 건축·모듈 조립용 실무 수치를 더한다.

| 규칙 | 수치 | 이유 |
| --- | --- | --- |
| 벽 두께 | 내벽 10~15 cm, 외벽 20~30 cm | 거리 필드 복셀보다 두꺼워야 한다 |
| 천장 슬래브 | 15~30 cm | 위층 빛이 아래로 새는 것을 막는다 |
| 조각 결합부 오버랩 | **5 cm 이상** 차폐 지오메트리 | 틈으로 새는 빛을 막는 겹침 |
| 이중벽 | 내벽·외벽 메시 분리(겹침 금지) | 겹치면 거리 필드가 깨진다 |
| 문 개구부 | 프레임이 벽을 **대체**(겹침 없이) | 프레임+벽 겹침 = 누광 |
| 양면 메시 | 사용 금지(내벽 별도 메시) | 거리 필드 "종이" 생성 |
| 거리 필드 | 큰 구조물만 `Affect Distance Field Lighting` | 빌드 시간·메모리 |
| 창 | 창틀 안쪽 Rect Light | 태양광만으로는 GI 부족 |

검증 절차:

1. `r.DistanceFields.Debug 1`로 벽의 거리 필드를 시각화한다. 벽이 점선처럼 끊겨 보이면 두께가 부족하다.
2. 실내를 완전히 어둡게(창문 가림) 하고, 밖에서 강한 방향광을 비춘다. 실내 벽에 밝은 얼룩이 보이면 누광이다.
3. 조각 건축이면 **결합부를 5 cm 겹쳐** 다시 배치한다. 인게임 건축에서 틈이 생기는 곳은 대부분 스냅 오차다(3.8.4).

```ini
; 거리 필드 해상도 상향(얇은 벽이 많은 모듈러 건축용)
r.DistanceFields.DefaultVoxelDensity=0.2
```

모듈 결합부 처리 두 가지 방법:

| 방법 | 내용 | 비용 |
| --- | --- | --- |
| 겹침 지오메트리 | 벽 끝에 5 cm 돌출된 "텅"을 넣어 이웃 벽과 겹친다 | 폴리곤 소량 |
| 코너 전용 부품 | 코너에서 겹침 없이 맞물리는 부품 | 킷 부품 증가 |
| 실링 스트립 | 결합부를 덮는 장식 띠(몰딩) | 폴리곤 최소, 시각적으로도 좋다 |

실무에서는 **코너 전용 부품 + 실링 스트립**을 기본으로 하고, 인게임 건축처럼 플레이어가 임의로 붙이는 경우에만 겹침 지오메트리를 둔다.

#### 3.9.6 디테일 예산: 건물 한 채 기준

| 요소 | 수치 | 비용 |
| --- | --- | --- |
| 모듈 수 | 30~60 | Nanite, 드로우콜 1~3 |
| 트림 시트 | 1장(2,048²) + 타일링 1~2장 | 텍스처 3장 |
| 머티리얼 | 1~2 슬롯 | 드로우콜 |
| 버텍스 컬러 레이어 | 3 | 샘플 3~6 |
| 데칼 | 8~20개(화면 내) | DBuffer 패스 |
| 패럴랙스 창 | 6~20개 | 반투명 |
| 광원 | 실내 3~5, 실외 1~2 | VSM 페이지 |
| 폴리곤 | 모듈 합계 60k~200k(Nanite) | — |

#### 3.9.7 폴리시 체크리스트

- [ ] 벽 모서리에 하이라이트가 있는가(가중치 노멀 또는 베벨)
- [ ] 트림 시트 UV가 띠 경계에서 새지 않는가(마진 ±2 px)
- [ ] 벽 아래쪽에 오염·이끼가 있는가(버텍스 컬러 또는 데칼)
- [ ] 모서리·계단참에 마모 데칼이 있는가
- [ ] 창문에 실내가 보이는가(패럴랙스 또는 실제 실내)
- [ ] 창문 근접 시 패럴랙스가 깨지지 않는가(창틀 마스크)
- [ ] 야간에 창문이 꺼져 죽어 보이지 않는가(발광·방 조명)
- [ ] 실내에서 빛샘이 없는가(두께·오버랩·거리 필드)
- [ ] 조각 결합부에 5 cm 겹침 또는 실링 스트립이 있는가
- [ ] 데칼 수가 화면당 예산 안인가
- [ ] 300 m에서 실루엣이 유지되는가(HLOD)

---

## 4. 배경과 레벨 드레싱

### 4.1 POI와 길찾기: 플레이어가 길을 아는 이유를 설계한다

오픈월드에서 플레이어가 미니맵을 보지 않고 이동할 수 있는 이유는 **랜드마크(landmark)** 때문이다. 월트 디즈니의 "위니(weenie)" 개념 — 멀리서 보이는 목표물이 사람을 끌고 간다 — 이 실무 용어로 쓰인다. 도시 이론에서는 Kevin Lynch의 도시 이미지 5요소(경로 Path, 경계 Edge, 지구 District, 결절점 Node, 랜드마크 Landmark)로 정리된다.

| 요소 | 게임에서의 구현 | 예시 |
| --- | --- | --- |
| 랜드마크 | 실루엣이 독특하고 300 m 밖에서도 식별되는 구조물 | 탑, 거대 나무, 다리, 폭포 |
| 결절점(Node) | 플레이어가 모이는 지점. 길의 교차·광장 | 마을 광장, 교차로 |
| 경로(Path) | 시각적으로 "이쪽으로" 안내하는 선 | 도로, 강, 성벽, 계곡 |
| 경계(Edge) | 이동을 막고 지구를 나누는 요소 | 절벽, 성벽, 큰 강 |
| 지구(District) | 재질·색·건축 양식으로 구분되는 영역 | 상업구(간판), 주거구(목조), 성채(석재) |

설계 절차:

1. **랜드마크를 먼저 배치한다.** 각 랜드마크에서 300/600/1,200 m 거리에서 실루엣이 구분되는지 스크린샷으로 확인한다(실루엣 테스트).
2. **랜드마크 사이의 시선을 연결한다.** A에서 B가 보이면 플레이어는 "저쪽"을 목표로 삼는다. 보이지 않게 하려면 지형으로 가린다 — 우연히 가려지면 길을 잃는다.
3. **지구마다 팔레트를 정한다.** 재질 2~3종 + 지배 색 1개. 지구 경계에 전환부(성문, 다리, 숲)를 둔다.
4. **경로에 "다음 목표"를 100~200 m 간격으로 둔다.** 시야에 항상 무언가 있게 하는 것이 길찾기 UI보다 강하다.

### 4.2 배치 워크플로우: 스냅 → 안착 → 검증

물리적으로 "떠 있는" 소품은 오픈월드에서 가장 흔한 품질 사고다(그림자와 접지가 어긋나 보인다). 배치 순서를 고정한다.

```
① 그리드 스냅    100 cm 그리드(소품은 10 cm)에 스냅. 회전은 15° 단위
② 지면 안착      End 키(바닥에 스냅) 또는 Sphere Trace로 지면에 내림
③ 기울기 보정    경사면은 노멀에 맞춰 회전(법선 정렬). 단, 수직 유지가 자연스러운 물체는 제외
④ 클러스터링     같은 종류를 3~7개 묶고, 크기 ±15 % 랜덤. 단일 배치는 어색하다
⑤ 물리 안착      동적 소품만 처음 0.5초 시뮬레이션 후 Kinematic 전환
⑥ HISM 변환      같은 메시 30개 이상이면 HISM으로 통합
⑦ 뷰 검증        플레이어 눈높이(165 cm)에서 캡처해 접지·겹침 확인
```

`End` 키 스냅이 안 되는 경우는 대개 **메시 피벗이 발밑이 아닌 경우**다. 0.2절의 피벗 규약을 어긴 에셋이 원인이므로, 예외를 만들지 말고 에셋을 고친다.

### 4.3 클러터와 인스턴싱

| 규칙 | 값 | 이유 |
| --- | --- | --- |
| HISM 전환 임계 | 같은 메시 30개 이상 | 30개 미만은 액터 오버헤드가 더 싸다 |
| 클러스터 크기 | 3~7개 | 1개는 부자연, 10개 이상은 노이즈 |
| 인스턴스당 회전 | 15° 단위, Y축 ±20° 랜덤 | 정렬된 인스턴스는 CG 티가 난다 |
| 스케일 랜덤 | 0.85~1.15 | 1.0 고정은 복제 티 |
| 컬 거리 | 소품 30~80 m, 대형 150 m | HISM 인스턴스 단위로 컬 |
| 물리 | 동적 소품은 초기 0.5초만 | 1,000개가 계속 시뮬레이션되면 물리 스레드 사망 |

HISM으로 바꾸면 개별 인스턴스에 이벤트·틱·오버랩을 붙일 수 없다. **상호작용이 필요한 소품은 HISM으로 만들지 않는다** — 30개 중 1개만 상호작용해도 그 1개는 액터로 남기고 나머지만 인스턴싱한다.

### 4.4 배경 밀도와 예산

배경은 "비어 보이지 않을 만큼" 채우되, 플레이어가 실제로 걸을 곳과 먼 배경을 구분한다.

| 거리 | 표현 | 예산 |
| --- | --- | --- |
| 0~30 m | 실물 소품 + 디칼 + 물리 | 화면 점유율 높음, 드로우콜 관리 |
| 30~120 m | 실물 소품(낮은 LOD) + HLOD 그룹 | 컬 거리 안 |
| 120~600 m | HLOD 프록시(병합 메시 + 임포스터) | 텍스처 1~2장, 저해상도 |
| 600 m+ | 배경 볼륨(스카이라인 메시, 스카이박스, 안개) | 폴리곤 최소, 라이팅 근사 |

이 경계를 넘나드는 순간에 HLOD 전환이 보이면 안 된다. 전환 지점은 지형·건물로 가리거나, 안개 밀도로 흐리게 한다.

### 4.5 레벨 드레싱 검증 체크리스트

- [ ] 모든 소품이 지면에 접지했는가(캡처 5장 이상에서 육안 확인)
- [ ] 같은 메시 30개 이상이 HISM으로 통합됐는가
- [ ] 상호작용 소품이 HISM에 섞이지 않았는가
- [ ] 컬 거리 밖에서 소품이 갑자기 사라지는 것이 보이지 않는가
- [ ] 물리 소품이 10초 뒤에도 계속 시뮬레이션되지 않는가
- [ ] 데칼 수가 화면당 예산(30~60) 이내인가
- [ ] 랜드마크가 300/600/1,200 m에서 식별되는가
- [ ] 셀 경계를 걸을 때 로딩 히치가 없는가(스트리밍 처리량은 `open_world_helper.py grid`로 확인)

---

## 5. 건축학 전문용어

건물을 "그럴듯하게" 만드는 것은 텍스처가 아니라 **부재가 구조적으로 말이 되는가**다. 아래 용어는 건축 실무에서 쓰는 말이고, 게임에서는 "이 부품이 왜 여기 있는가"를 설명하는 언어가 된다. 킷 부품 이름에 이 용어를 쓰면 아티스트·기획·개발이 같은 것을 가리킨다.

### 5.1 구조 부재

| 한글 | 영문 | 정의 | 게임 제작에서 |
| --- | --- | --- | --- |
| 기둥 | Column / Pillar | 수직 하중을 받는 부재. 하중을 기초로 전달 | 구조 그리드의 기준점. 간격이 평면을 결정한다 |
| 보 | Beam | 수평으로 걸쳐 하중을 기둥·벽으로 전달 | 노출 천장의 리듬. 방 높이를 낮추는 요소 |
| 트러스 | Truss | 삼각형 단위로 조합한 경량 구조체. 장스팬 지붕·교량 | 지붕·교량·산업 건물의 실루엣 |
| 내력벽 | Bearing Wall | 하중을 직접 받는 벽. 함부로 뚫을 수 없다 | "여기는 창문이 없어야 한다"는 설계 근거 |
| 슬래브 | Slab | 바닥·지붕의 판 구조 | 층고 = 슬래브 두께 + 층 높이 |
| 캔틸레버 | Cantilever | 한쪽만 지지된 외팔보 구조 | 발코니·차양·절벽 위 건물. 긴장감 연출 |
| 필로티 | Pilotis | 1층을 비우고 기둥으로 띄운 구조 | 1층 필로티 = 자연스러운 통로·차량 진입 |
| 아치 | Arch | 곡선으로 하중을 분산하는 구조 | 성문·수로·교량. 반원/첨두/세그먼트 아치 |
| 볼트 | Vault | 아치를 길게 늘인 천장 구조 | 지하·성당·창고 |
| 돔 | Dome | 반구형 지붕 | 랜드마크(5.1의 랜드마크 역할) |
| 버트레스 | Buttress | 벽을 바깥에서 버티는 지지 구조 | 성당·성벽의 측면 리듬 |
| 플라잉 버트레스 | Flying Buttress | 아치로 띄운 버트레스 | 고딕 성당의 상징적 실루엣 |
| 린텔 | Lintel | 개구부 위에 걸친 수평 부재 | 문·창 상단. 나무/석재 두께로 표현 |
| 키스톤 | Keystone | 아치 정상의 마지막 돌 | 아치의 시각적 중심 |
| 부쇠 | Voussoir | 아치를 구성하는 쐐기형 돌 | 아치 켜의 텍스처 리듬 |
| 주두 / 기둥몸체 / 기단 | Capital / Shaft / Base | 기둥의 머리·몸통·발치 | 오더 구분의 핵심(5.2) |
| 엔타시스 | Entasis | 기둥 중앙을 미세하게 부풀린 곡선 | 근접 시 "고급스러움"을 만드는 디테일 |
| 스팬 | Span | 지지점 사이 거리 | 경간 표(8.4) |

### 5.2 공간·입면

| 한글 | 영문 | 정의 | 게임 제작에서 |
| --- | --- | --- | --- |
| 파사드 | Façade | 건물의 외부 정면 | 플레이어가 가장 오래 보는 면. 여기에 예산을 몰아준다 |
| 아트리움 | Atrium | 건물 내부의 큰 개방 공간(천창 포함) | 실내 랜드마크, 수직 시선 |
| 중정 | Courtyard | 건물이 둘러싼 외부 마당 | 소규모 오픈 스페이스, 채광 |
| 코니스 | Cornice | 벽 상단에서 튀어나온 수평 띠 | 층을 구분하는 가로선. 파사드 리듬의 핵심 |
| 엔타블러처 | Entablature | 기둥 위의 수평부(아키트레이브+프리즈+코니스) | 고전 양식의 상부 3분할 |
| 플린스 | Plinth | 기둥·벽의 바닥 받침 | 벽 하단의 어두운 띠. 오염을 가리는 기능도 |
| 루버 | Louver | 빗살 모양의 통풍·차양 부재 | 기계실·탑·창의 반복 패턴 |
| 커튼월 | Curtain Wall | 하중을 받지 않는 유리 외피 | 현대 도시 건물. 반사/투명 예산 주의 |
| 멀리언 | Mullion | 창을 세로로 나누는 부재 | 창의 세로 리듬, 유리 분할 |
| 트랜섬 | Transom | 창을 가로로 나누는 부재 | 상부 개폐창 |
| 스팬드럴 | Spandrel | 아치 사이·층 사이의 채움 벽 | 층별 띠 장식 |
| 파라펫 | Parapet | 지붕 가장자리의 낮은 벽 | 옥상 접근 차단, 실루엣 |
| 발루스트레이드 | Balustrade | 난간동자로 구성된 난간 | 발코니·계단의 장식 난간 |
| 소핏 | Soffit | 처마·보 아래의 노출면 | 아래에서 올려다볼 때 보이는 면(UV 필수) |
| 클레스토리 | Clerestory | 지붕 위쪽의 고창 | 성당·산업 건물의 상부 채광 |
| 콜로네이드 | Colonnade | 일렬의 기둥 회랑 | 광장·신전의 리듬 |
| 아케이드 | Arcade | 아치 열로 된 회랑 | 상가·수도원. 통로를 만든다 |
| 페디먼트 | Pediment | 지붕 끝의 삼각형 박공면 | 고전 건물의 정면 상징 |
| 포르티코 | Portico | 건물 입구의 기둥 현관 | 진입의 위계 |
| 브리즈솔레이 | Brise-soleil | 차양 격자 | 더운 지방 건축, 반복 그림자 |
| 베이 | Bay | 기둥·벽 사이의 한 구획 | 모듈러 설계의 기본 단위(8.1) |
| 오리엘 / 돌출창 | Oriel / Bay Window | 벽에서 돌출한 창 | 입면의 변화 |
| 코너스톤 / 모서리돌 | Quoin | 모서리를 강조하는 돌 | 코너 부품의 장식 |
| 아시라 | Ashlar | 정교하게 쌓은 사각 돌 | 석조 벽의 켜 |
| 러스티케이션 | Rustication | 1층 외벽의 거친 돌 쌓기 | 하부를 무겁게 보이게 하는 기법 |

### 5.3 장식·재료

| 한글 | 영문 | 정의 | 게임 제작에서 |
| --- | --- | --- | --- |
| 덴틸 | Dentil | 코니스 아래 이빨 모양 장식 | 1~2 cm 반복. 노멀맵으로 대체 권장 |
| 모딜리언 | Modillion | 코니스를 받치는 장식 브래킷 | 코니스 하부 리듬 |
| 볼류트 | Volute | 이오니아·코린트 기둥머리의 소용돌이 | 근접 히어로 건물만 |
| 아칸서스 | Acanthus | 코린트 기둥머리의 잎 장식 | 스컬프트/노멀맵 |
| 프리즈 | Frieze | 엔타블러처의 중간 띠 | 부조·문양 띠 |
| 트리글리프 / 메토프 | Triglyph / Metope | 도리아식 프리즈의 교대 요소 | 반복 패턴의 고전적 예 |
| 크로켓 / 피나클 | Crocket / Pinnacle | 고딕 첨탑의 잎 장식 / 끝 뾰족탑 | 성당 실루엣 |
| 가고일 | Gargoyle | 낙수구 조각 | 성당·성의 캐릭터성 |
| 조적 | Masonry | 돌·벽돌을 쌓는 시공 | 벽 텍스처의 기본 어휘 |
| 코스 | Coursing | 조적의 켜(수평 줄) | 텍스처 스케일 기준(벽돌 1켜 7.5 cm) |
| 줄눈 | Mortar Joint | 벽돌 사이 접합부 | 노멀맵의 홈 |
| 스트레처 본드 | Stretcher Bond | 벽돌을 길게 쌓는 방식 | 가장 흔한 패턴 |
| 플레미시 본드 | Flemish Bond | 길이/머리 번갈아 쌓기 | 장식적 패턴 |
| 철근콘크리트 | Reinforced Concrete | RC | 현대 건물의 기본 |
| 철골 | Steel Frame | 강구조 | 공장·고층·장스팬 |
| CLT | Cross-Laminated Timber | 교차 접합 목재 패널 | 목조 고층, 친환경 건축 |
| 슁글 | Shingle | 지붕의 겹침 판재 | 목조 지붕 |
| 청동 | Bronze | 청동 | 문·조각·장식. 세월의 변화(녹청)를 버텍스 블렌드로 |
| 스투코 | Stucco | 회벽 마감 | 지중해풍 건물 |

### 5.4 한국 전통 건축 용어

한국적 배경을 만들 때 서양 용어로 번역하면 어색해진다. 전통 부재는 별도 킷으로 만드는 것이 맞다.

| 한글 | 대응 | 설명 |
| --- | --- | --- |
| 기와 | Roof Tile | 암키와(수키와 아래 평평한 기와)와 수키와(볼록한 기와)의 교대 |
| 처마 | Eave | 지붕이 벽 밖으로 나온 부분. 곡선 처마가 한국 건축의 실루엣 |
| 맞배지붕 / 우진각지붕 / 팔작지붕 | Gable / Hip / Hip-and-Gable | 지붕 형식. 팔작지붕이 가장 화려하고 제작 비용이 크다 |
| 공포 | Bracket System | 기둥 위에서 처마를 받치는 복잡한 목조 조립체 |
| 주두 | Column Capital | 기둥 위의 받침 |
| 대청 | Main Hall (Maru) | 마루로 된 중심 공간. 여름의 생활 공간 |
| 온돌 | Ondol | 바닥 난방. 방의 바닥이 낮고 아궁이가 외벽에 붙는다 |
| 마루 | Maru | 나무 바닥의 마루. 방보다 30~60 cm 높다 |
| 사랑채 / 안채 / 행랑채 | Sarangchae / Anchae / Haengrangchae | 남성 공간 / 여성 공간 / 하인·창고 |
| 누각 | Pavilion (Nu) | 2층 마루 구조의 정자·문루 |
| 정자 | Jeongja | 경치를 보는 개방 정자 |
| 홍예 | Arch (Hongye) | 성문의 아치. 홍예문 |
| 성문 / 옹성 | Gate / Barbican | 성의 출입구 / 문을 감싸는 이중 성벽 |
| 담장 | Wall (Dam) | 돌·흙·기와로 만든 경계벽 |

전통 건축에서 제작 비용이 가장 큰 부분은 **공포(기둥 위 처마 받침)**의 반복 조립이다. 공포는 1D 부재 세트로 만들어 HISM으로 반복하고, 근접 관찰이 필요한 곳(현판 주변, 누각)만 개별 메시로 만든다.

### 5.5 오더(Order)와 시대 양식 — "어떤 건물인가"를 결정하는 최상위 값

| 양식 | 핵심 비례 | 표정 | 게임 적합 |
| --- | --- | --- | --- |
| 도리아 | 기둥 지름 대비 높이 6:1, 장식 최소 | 무겁고 남성적 | 성채·관공서·병영 |
| 이오니아 | 9:1, 볼류트 주두 | 우아하고 여성적 | 신전·도서관·궁전 |
| 코린트 | 10:1, 아칸서스 잎 주두 | 화려 | 신전·궁전·극장 |
| 로마네스크 | 두꺼운 벽, 작은 창, 반원 아치 | 요새 같은 교회 | 수도원·성당·요새 |
| 고딕 | 첨두 아치, 플라잉 버트레스, 수직성 | 상승·경외 | 대성당·성당 도시 |
| 르네상스 | 대칭, 비례, 고전 오더의 재해석 | 균형·질서 | 궁전·광장·저택 |
| 바로크 | 곡선, 과장, 빛의 극장 | 극적·감정적 | 극장·성당·정원 |
| 신고전주의 | 단순화된 고전, 대칭 | 권위·기념비 | 정부 청사·박물관 |
| 산업/모더니즘 | 장식 없음, 기능, 유리·철·콘크리트 | 효율·냉정 | 공장·창고·현대 도시 |
| 폐허/포스트아포칼립스 | 구조 노출, 붕괴, 식생 침범 | 상실·생존 | 폐허 도시·던전 표면 |

양식은 **재질 2종 + 비례 1개 + 장식 밀도 1개**로 요약된다. 프로젝트의 건축 팔레트를 이 세 축으로 문서화하면, 새 건물을 만들 때 "고딕이니까 첨두 아치 + 수직 분절 + 장식 3단"처럼 즉시 결정할 수 있다.

---

## 6. 도면의 종류와 도면 규약

### 6.1 도면 종류

| 도면 | 영문 | 축척 | 무엇을 정하는가 | 게임에서의 쓰임 |
| --- | --- | --- | --- | --- |
| 배치도 | Site Plan | 1:500~1:1,000 | 대지·건물·도로·조경의 관계 | 마을/구역 배치, POI 위치 |
| 평면도 | Floor Plan | 1:100 (부분 1:50) | 벽·문·창·가구의 수평 배치 | 블록아웃의 기준. 가장 중요한 도면 |
| 반사천장평면도 | Reflected Ceiling Plan | 1:100 | 천장 마감·조명·설비 | 실내 라이팅 배치 |
| 입면도 | Elevation | 1:100 | 각 면의 높이·창·장식 | 파사드 모델링, 실루엣 |
| 단면도 | Section | 1:100 (부분 1:20) | 층고·천장·지붕·구조의 수직 관계 | 층고 검증, 계단·경사 |
| 상세도 | Detail | 1:10~1:1 | 접합·마감·프로파일 | 몰딩·창틀 트림 시트 |
| 확대평면도 | Enlarged Plan | 1:50~1:20 | 화장실·계단실·주방 | 작은 방의 정밀 배치 |
| 지붕평면도 | Roof Plan | 1:100~1:200 | 지붕 형식·경사·배수 | 지붕 킷 설계 |
| 실내 입면도 | Interior Elevation | 1:50 | 벽면의 가구·마감 | 상점·주거 실내 |
| 전개도 | Unfolded Elevation | 1:50 | 방 4면을 펼친 도면 | 실내 드레싱 |
| 창호 일람표 | Door/Window Schedule | — | 문·창의 규격·수량 | 킷 부품 목록의 원천 |
| 마감 일람표 | Finish Schedule | — | 재료·색·마감 | 머티리얼 인스턴스 목록 |
| 분해도 | Exploded View | — | 부품의 조립 관계 | 모듈러 킷 문서 |
| 다이어그램 | Diagram | — | 동선·구조·개념 | 기획서의 공간 설명 |

게임 제작에서 실제로 쓰이는 순서는 **평면도 → 단면도 → 입면도**다. 평면으로 공간의 크기를 정하고, 단면으로 층고와 높이를 검증하고, 입면으로 겉모습을 만든다. 이 순서를 뒤집으면(입면부터 그리면) 실내가 안 들어간다.

### 6.2 도면 규약

| 요소 | 규약 | 게임에서의 대응 |
| --- | --- | --- |
| 그리드 | 세로 A·B·C, 가로 1·2·3 (버블 표기) | 모듈러 그리드의 이름. `Grid_A_1` 액터 명명 |
| 레벨 기호 | EL ±0.000, FFL(마감 바닥), SSL(구조 바닥), TOS(구조 상단) | 액터 Z 좌표 기준. 마감 5 cm 차이를 무시하면 문턱이 생긴다 |
| 치수 | mm 단위, 마감면 기준 | 1 uu = 1 cm이므로 mm 값 ÷ 10 |
| 해치 | 콘크리트(점), 벽돌(사선), 단열재(지그재그), 흙(삼각) | 재질 구분 표시 |
| 절단선 | 단면 위치와 보는 방향 | 카메라 컷 설계 |
| 창호 기호 | 문·창의 개폐 방향, 유리 종류 | 열림 애니메이션 방향 |
| 실명·면적 | 방 이름 + 면적(㎡) | 레벨 액터의 태그·Data Layer 이름 |

### 6.3 도면을 게임으로 옮기는 워크플로우

```
CAD 도면(DWG/DXF) 또는 스케치
   → ① 1:100 평면도를 PNG로 내보내고 기준 치수(예: 외벽 12,000 mm)를 기록
   → ② 블렌더/언리얼에 이미지 플레인으로 깔고 1:1 스케일로 맞춘다
        (이미지 폭 px → 1,200 cm가 되도록 스케일 = 1200 / 이미지 폭)
   → ③ 벽 중심선을 따라 큐브로 블록아웃(graybox). 이 단계에서 디테일 0
   → ④ 캐릭터 캡슐로 걸어보며 문·복도·계단 폭 검증(7장 수치)
   → ⑤ 킷으로 치환. 블록아웃의 치수를 그대로 유지
   → ⑥ 입면도로 파사드 부품 배치, 단면도로 층고·지붕 확정
```

③에서 ④를 건너뛰는 것이 가장 흔한 실수다. 도면상 900 mm 문은 사람에게는 맞지만, 3인칭 카메라와 68 cm 캡슐에게는 좁다(7.2절).

---

## 7. 인간공학 치수 vs 게임 스케일

### 7.1 왜 다른가

실제 건축 치수는 **1인칭 시점의 인간**을 기준으로 한다. 게임은 다음 세 가지가 추가된다.

1. **캐릭터 캡슐**이 몸보다 크다. UE 기본 3인칭 캐릭터는 반경 34 cm(지름 68 cm)다. 실제 사람 어깨 폭 45 cm보다 넓다.
2. **3인칭 카메라**가 캐릭터 뒤 300~400 cm에 떠 있다. 문틀을 통과할 때 카메라가 벽에 걸리면 시점이 튄다.
3. **이동 속도**가 빠르다. UE 기본 `MaxWalkSpeed` 600 cm/s는 21.6 km/h로, 실제 조깅보다 빠른 달리기다. 좁은 공간에서 초당 6 m를 이동하면 벽에 부딪히는 빈도가 높다.

그래서 게임 건축은 **인간공학 치수의 상한에 카메라·캡슐 마진을 더한 값**을 쓴다.

### 7.2 대응 치수표

| 요소 | 실제 건축 (mm) | 게임 권장 (cm, 1인칭) | 게임 권장 (cm, 3인칭) | 근거 |
| --- | --- | --- | --- | --- |
| 단일 문 폭 | 800~900 | 90~100 | **120~150** | 캡슐 68 + 좌우 마진 25~40 |
| 복도 폭 | 1,200 (최소 900) | 120~150 | **180~240** | NPC 통행 + 카메라 |
| 천장 높이(주거) | 2,400 | 260~280 | **300~350** | 스프링암 300~400의 상방 시선 |
| 천장 높이(공공) | 2,800~3,500 | 300~350 | 350~450 | |
| 층고(바닥~바닥) | 3,000~3,300 | 320~340 | **340~380** | 슬래브 30 포함 |
| 계단 단높이(Riser) | 170~180 | 17~18 | **17~18** | CMC `MaxStepHeight` 45 이하 |
| 계단 디딤판(Tread) | 260~280 | 28~30 | **28~32** | |
| 계단 유효폭 | 1,200 | 120 | **150~200** | NPC 통행 |
| 난간 높이 | 900 (계단), 1,100 (발코니) | 90~110 | 110 | 점프 높이 90 cm와 함께 본다 |
| 문턱 높이 | 0~20 | 0 | **0~15** | 45 cm 이하는 넘지만 걸린다 |
| 램프 경사 | 1:12 (8.3 %) | 1:10 | 1:6~1:8 | 걸어 올라가는 게임은 완만해야 |
| 가구: 의자 좌고 | 450 | 45 | 45~50 | |
| 가구: 테이블 높이 | 720~750 | 72~75 | 75 | |
| 카운터 높이 | 900~1,050 | 100 | 105 | |
| 침대 | 2,000×1,000 | 200×100 | 200×110 | |
| 엘리베이터 | 1,600×1,500 | 200×200 | **250×250** | 캐릭터 + 카메라 |
| 차량 문(승하차) | 900 | — | 110~130 | 캐릭터 캡슐이 지나갈 수 있는가 |

3인칭 카메라 마진의 실무 공식:

```
필요 문 폭 ≥ 캡슐 지름(68) + 2 × 카메라 마진(25~40) = 118~148 cm
필요 복도 폭 ≥ 필요 문 폭 + 60 (양옆 소품·문틀 여유) = 180~210 cm
```

### 7.3 계단: 공식 하나로 끝난다

계단 설계의 기본식은 **2R + T = 600~640 mm**(블롱델 공식)이다. 단높이 R과 디딤판 T의 합이 사람 보폭에 맞아야 오르기 편하다.

| 용도 | R (단높이) | T (디딤판) | 2R+T | 경사 |
| --- | --- | --- | --- | --- |
| 주거(완만) | 170 | 290 | 630 | 30.4° |
| 공공(표준) | 150 | 300 | 600 | 26.6° |
| 게임(3인칭 기본) | 175 | 300 | 650 | 30.3° |
| 게임(빠른 이동) | 180 | 320 | 680 | 29.4° |
| 성·탑(급경사) | 200 | 250 | 650 | 38.7° |

경사각은 `atan(R/T)`다. **UE CMC 기본 `WalkableFloorAngle`은 44.76°** 이므로 38.7°까지는 걸어 올라갈 수 있다. 45°를 넘으면 캐릭터가 미끄러진다(올라가지 못한다). 성벽 내부 계단처럼 급한 곳은 40°를 넘기지 않는다.

층고에서 계단을 계산하는 절차:

```
① 층고(바닥~바닥) 결정              예: 340 cm
② 목표 단높이로 단수 계산          340 / 17.5 = 19.4 → 19단 또는 20단
③ 실제 단높이 확정                 340 / 20 = 17.0 cm   (정수로 나누어떨어지게)
④ 디딤판 결정                      30 cm (2R+T = 64 → 640, 허용 범위)
⑤ 계단 진행 길이                   (20-1) × 30 = 570 cm   ← 마지막 단은 바닥
⑥ 착지참(landing) 포함 총 길이     570 + 120(상부 착지) + 0~120(하부) = 690~810 cm
⑦ 계단실 폭                       계단 150 + 난간 10 + 벽 15 = 175 cm (직선)
```

19단이면 340/19 = 17.9 cm로 허용 범위 안이다. **층고를 단수로 나누어떨어지게 만드는 것**이 핵심이다. 안 그러면 마지막 단만 18.4 cm가 되어 발이 걸린다.

꺾인 계단(U자/ㄱ자)은 착지참을 120~150 cm로 잡고 폭을 2배로 한다. 2층 건물의 계단실은 대략 **폭 350~400 cm × 길이 400~500 cm**를 차지한다고 보고 평면에 먼저 자리를 비워 둔다.

### 7.4 캐릭터와 스케일 검증

| 검증 항목 | 방법 | 통과 기준 |
| --- | --- | --- |
| 문 통과 | 캐릭터로 정면·대각선 통과 | 걸림·카메라 튐 없음 |
| 계단 오르기 | 20단 연속 상승 | 미끄럼·모서리 걸림 없음, 바운스 없음 |
| 난간 넘기 | 점프로 난간 넘기 시도 | 의도한 곳만 넘어짐(110 cm 난간은 못 넘음) |
| 천장 | 실내에서 카메라 최대 상향 | 벽 관통·클리핑 없음 |
| 가구 | 의자 앉기·테이블 통과 | 캡슐이 가구에 끼지 않음 |
| 차량 승하차 | 문 옆에서 승차 | 캐릭터가 차체에 끼지 않음 |

`MaxStepHeight`(기본 45)와 `WalkableFloorAngle`(기본 44.76°)은 프로젝트 설정값이므로, 건축 킷을 만들기 전에 **이 두 값을 확정하고 문서화**한다. 나중에 45→30으로 낮추면 모든 계단이 다시 만들어진다.

---

## 8. 모듈러 건축 설계 방법론

### 8.1 표준 그리드

| 그리드 | 쓰임 | 배수 관계 | 비고 |
| --- | --- | --- | --- |
| **100 cm** | 벽 길이·문·개구부 | 기본 단위 | 모든 부품의 최소 분할 |
| **200 cm** | 창·계단 폭·소품 | 2×100 | 창과 난간의 리듬 |
| **400 cm** | 방·바닥 패널 | 4×100, 2×200 | 방 하나의 최소 모듈 |
| **500 cm** | 구조 경간·복도 | 5×100 | 목조·중목구조의 자연 경간 |
| **600~800 cm** | 기둥 간격(대형 홀) | 6~8×100 | RC/강구조 장스팬 |

이 다섯 단계가 서로 배수로 맞물려야 한다. 100과 500만 쓰고 200을 안 쓰면 창 배치가 어색해지고, 400과 600을 섞으면 방과 방이 100 cm씩 어긋난다.

**그리드 선택 규칙**: 건물 유형이 그리드를 정한다.

| 건물 유형 | 주 그리드 | 이유 |
| --- | --- | --- |
| 주거(소형) | 300~400 | 방 3~4개가 한 층에 들어가는 크기 |
| 주거(중형·아파트) | 400~500 | 세대 모듈 |
| 상점·여관 | 400 | 진열·객실 단위 |
| 사무실 | 600~800 | 책상 배치와 기둥 간격 |
| 공장·창고 | 800~1,200 | 장비·차량 통행 |
| 성당·사원 | 500~600 | 신랑(nave) 경간 |
| 성채·탑 | 200~300 | 벽 두께가 두껍고 공간이 작다 |

### 8.2 평면 계획법

평면은 **베이(bay) 격자에 방을 채우는 일**이다. 400 cm 베이를 기준으로 방 크기를 조합한다.

| 방 | 베이 조합 | 크기 (cm) | 비고 |
| --- | --- | --- | --- |
| 소형 침실 | 2×2 | 800×800 | 침대 200 + 통로 60 × 2 |
| 표준 침실 | 2×3 | 800×1,200 | |
| 거실 | 3×4 | 1,200×1,600 | 소파·테이블·동선 |
| 주방 | 2×2 | 800×800 | 작업 삼각형(냉장고-싱크-레인지) |
| 상점 | 3×4 | 1,200×1,600 | 카운터 + 진열 |
| 홀/로비 | 4×6 | 1,600×2,400 | 아트리움 가능 |
| 회랑(복도) | 1×N | 400 폭 | 3인칭은 200 이상 필요(7.2) |

평면 계획 순서:

1. **외곽선(매스)을 그린다.** 그리드 배수 사각형.
2. **주 진입과 동선을 한 줄로 긋는다.** 입구 → 중심 → 목표(계단·주요 방). 이 선이 꺾이면 플레이어가 길을 잃는다.
3. **복도를 깐다.** 폭 200(게임) 또는 400(대형). 복도는 방 배치의 나머지 공간을 결정한다.
4. **방을 채운다.** 큰 방(공용)은 입구 근처, 작은 방(개인)은 안쪽.
5. **개구부를 뚫는다.** 모든 방은 문 1개 + 창 1개 이상(채광·시야). 문이 마주 보면 동선이 좋고, 마주 보지 않으면 사생활이 생긴다 — 게임에서는 "마주 보게" 만드는 것이 시야 확보에 유리하다.

### 8.3 입면과 층고

층고는 세 값의 합이다.

```
층고 = 층 높이(바닥 마감~천장 마감) + 슬래브 두께 + 마감 두께
예:   300 (거실) + 30 (슬래브) + 5 (마감) = 335 cm
```

| 요소 | 값 | 비고 |
| --- | --- | --- |
| 층 높이(주거) | 260~280 | 실제 |
| 층 높이(게임 3인칭) | 300~350 | 카메라 |
| 슬래브 | 20~30 | RC 200~300 mm |
| 바닥 마감 | 3~10 | 타일·목재 |
| 천장 마감(반자) | 20~40 | 설비 공간 |

입면(파사드) 구성 원칙:

- **3분할**: 하부(기단·플린스) / 중부(창·벽) / 상부(코니스·지붕). 비율 1:3:1 또는 1:2:1. 이 수평선이 없으면 파사드가 "상자"로 보인다.
- **수직 분절**: 기둥·필라스터로 세로 리듬. 1 베이(400)마다 하나.
- **개구부 비율**: 창의 가로:세로 = 1:1.2~1:1.5. 정사각 창은 근대적, 세로로 긴 창은 고딕적, 가로로 긴 창은 현대적.
- **반복과 예외**: 같은 창 8개 + 다른 창 1개(입구). 예외가 없으면 건물이 배경으로 사라진다.
- **모서리 처리**: 코너 부품(코너스톤·필라스터)으로 마감. 모서리가 열려 보이면 조립 실패다.

### 8.4 구조 그리드와 경간

| 구조 | 자연 경간 | 최대 경간 | 게임에서의 의미 |
| --- | --- | --- | --- |
| 목조(경량) | 3~5 m | 6 m | 기둥 간격 400~500. 촘촘한 리듬 |
| 중목구조/CLT | 5~8 m | 12 m | 600~800 |
| 철근콘크리트 | 6~8 m | 12 m | 600~800. 가장 표준적 |
| 철골 | 8~12 m | 30 m+ | 800~1,200. 산업 건물 |
| 아치·트러스 | 15~40 m | 100 m+ | 홀·교량. 랜드마크급 |

게임에서는 **기둥 간격이 넓을수록 이동·전투가 편하다.** 600~800 cm가 3인칭 전투의 스윗스팟이고, 400 cm는 "좁은 실내" 느낌을 준다. 기둥이 200 cm 간격이면 캐릭터가 계속 걸린다.

### 8.5 지붕 형식

| 형식 | 영문 | 경사 | 특징 | 게임 비용 |
| --- | --- | --- | --- | --- |
| 평지붕 | Flat | 1/50~1/100 | 물막이 필요, 파라펫 | 낮음 |
| 맞배지붕 | Gable | 25~45° | 가장 흔한 경사지붕, 박공면 | 낮음 |
| 우진각지붕 | Hip | 25~35° | 네 면 모두 경사 | 중간 |
| 팔작지붕 | Hip-and-Gable | 30~40° | 한국·동아시아, 곡선 처마 | 높음(부재 다수) |
| 단경사 | Shed/Mono-pitch | 5~20° | 창고·산업, 방향성 | 낮음 |
| 원추/첨탑 | Conical/Spire | 45~70° | 탑·첨탑, 랜드마크 | 중간 |
| 볼트·돔 | Vault/Dome | — | 성당·궁전 | 높음 |

경사는 기능에서 온다: 눈이 내리는 지역은 35~45°, 비가 많은 지역은 25~35°, 건조 지역은 10~20°. 이 규칙을 따르면 바이옴과 건축이 일치한다.

### 8.6 킷 조립과 스냅 규약

| 규약 | 값 | 비고 |
| --- | --- | --- |
| 그리드 스냅 | 10 uu(10 cm) | 언리얼 뷰포트 Grid Snap |
| 액터 스냅 | 100 uu | 벽·바닥 모듈 |
| 소켓 | `Snap_N`, `Snap_S`, `Snap_E`, `Snap_W`, `Snap_Top`, `Snap_Bottom` | 6방향 소켓으로 이어 붙인다 |
| 피벗 | 벽: 하단 좌측 모서리 / 바닥: 중심 / 계단: 하단 전면 중앙 | 0.2절 |
| 회전 | 90° 단위 | 대각 배치는 별도 부품 |
| 겹침 | 0 | 부품이 겹치면 거리 필드·라이팅이 깨진다(3.3) |

언리얼에서는 소켓 스냅(Socket Snapping)과 버텍스 스냅(V)으로 조립한다. 대량 조립은 여전히 수동이지만, **같은 건물을 Level Instance로 복제**하면 손 작업이 1회로 줄어든다.

### 8.7 텍스처·머티리얼 설계

| 설계 | 내용 | 수치 |
| --- | --- | --- |
| 트림 시트 | 세로 2,048 px에 8~12개 프로파일 띠 | 띠당 170~256 px |
| 텍셀 밀도 | 트림 시트 1장이 4 m 벽을 덮을 때 512 px/m | 2,048/4 m = 512 |
| 타일링 머티리얼 | 벽돌·콘크리트 기본 면 | 1,024 또는 2,048, 2 m 타일 |
| 매크로 배리에이션 | 대형 노이즈로 색·거칠기 변화 | 4~16 m 스케일 |
| 버텍스 블렌드 | R=이끼, G=오염, B=균열 | 마스크 3채널 |
| 디칼 | 낙서·물자국·피 | 화면당 30~60 |
| 마스터 머티리얼 수 | 2~3개(벽/바닥/장식) | 스위치 대신 파라미터 |

트림 시트 UV 배치는 **모듈마다 UV를 띠 하나에 맞추는** 작업이다. 부품 1개에 3개 띠(상단 몰딩·벽면·하단 플린스)를 쓰면 자연스럽다.

### 8.8 킷 검증 절차

1. **1실 테스트**: 벽 4개 + 문 1개 + 창 1개 + 바닥 + 천장을 조립한다. 30분 안에 되지 않으면 킷 설계가 틀렸다.
2. **계단실 테스트**: 층고 340에 계단을 넣고 2층까지 오른다. 단수 계산(7.3)과 실제 메시가 일치하는지.
3. **20채 테스트**: 같은 킷으로 20채를 만든다. 20채가 서로 "다르게" 보이지 않으면 변주 부품(베이 수·지붕·색)이 부족하다.
4. **거리 테스트**: 300/600/1,200 m에서 스크린샷. 실루엣이 구분되는가.
5. **성능 테스트**: 20채를 한 화면에 두고 GPU 프로파일. 드로우콜·머티리얼 스위치·Nanite 클러스터 수를 기록.

---

## 9. 제작 로드맵과 검증 게이트

콘텐츠 4종(탈것·아이템·건물·배경)은 서로 의존한다. 순서를 정하지 않으면 "차가 들어갈 문이 없는 도시"가 나온다.

| 단계 | 기간(예시) | 산출물 | 통과 게이트 |
| --- | --- | --- | --- |
| 0. 규약 | 1주 | 단위·피벗·명명·예산표(0.2, 0.3) | 전원이 같은 그리드로 에셋을 낸다 |
| 1. 건축 그리드·킷 | 3~4주 | 벽·바닥·계단·지붕 킷, 1실 테스트 | 1실 테스트 30분 이내, 계단 오르기 통과 |
| 2. 건물 20채 | 3주 | 마을 1개, Level Instance | 20채 변주, 300 m 실루엣 |
| 3. 배경·POI | 2주 | 랜드마크 5개, 시선 연결 | 300/600/1,200 m 식별 |
| 4. 아이템 데이터 | 2주 | `UItemDefinition` 100종, 상호작용 | 자동 검증(중복 ID 0, 아이콘 100 %) |
| 5. 탈것 | 3~4주 | 차량 3종, 승하차, AI 주행 | 멀티 4인에서 운전자 조작 지연 체감 없음 |
| 6. 통합 | 2주 | 마을 + 차량 + 아이템 + NPC | 셀 경계 히치 0, 60 fps 유지 |
| 7. 최적화 | 2주 | HLOD, 컬, 라이트 토글 | 기기 프로파일별 프레임 예산 내 |

게이트를 통과하지 못하면 다음 단계로 넘어가지 않는다. 특히 **1단계(킷)**를 건너뛰고 건물을 만들면 2단계에서 킷을 다시 만들게 된다.

---

## 10. 자주 터지는 지점

| 증상 | 원인 | 진단 | 조치 |
| --- | --- | --- | --- |
| 에셋이 100배 크거나 작다 | DCC 단위(m) vs 언리얼(cm) | 임포트 창의 스케일 확인 | DCC 익스포트 설정 고정, 재임포트 |
| 소품이 떠 있다 | 피벗이 중심, `End` 키 미사용 | 와이어프레임으로 접지 확인 | 피벗 재설정 또는 액터 Z 보정 |
| 벽 사이로 빛이 샌다 | 벽 두께 < 10 cm, 양면 메시, 부품 겹침 | 거리 필드 시각화(`r.DistanceFields.Debug 1`) | 두께 증가, 내벽 별도 메시 |
| 실내가 너무 어둡다 | 창 Rect Light 없음, Lumen GI 부족 | 광원 목록 확인 | 창 Rect Light + 이미시브 보조 |
| 문 앞에서 캐릭터가 걸린다 | 문 폭 90 cm, 캡슐 68 cm | 캡슐 표시(`Show Collision`) | 문 120~150으로 교체 |
| 계단에서 미끄러진다 | 경사 > 44.76°, `WalkableFloorAngle` | 경사각 계산 | 단높이/디딤판 조정 또는 설정 변경 |
| 계단 오를 때 화면이 튄다 | 단높이가 `MaxStepHeight`에 근접, 캡슐 보간 | `MaxStepHeight` 확인 | 단높이 18 이하, `bEnableScopedMovementUpdates` 확인 |
| 같은 메시 500개에서 프레임 하락 | HISM 미적용 | 드로우콜 통계 | HISM 변환, 컬 거리 |
| 배경이 갑자기 사라진다 | 컬 거리, HLOD 전환 | 컬 거리 볼륨 확인 | 컬 거리 확대 또는 안개로 가림 |
| 물리 소품이 계속 떨린다 | 시뮬레이션 지속, 질량 과소 | 물리 상태 확인 | 0.5초 후 Kinematic, 질량 보정 |
| 차가 스폰 즉시 폭발 | 바퀴 본 위치·질량 | 로그의 spring 경고 | 1.2절 규약 |
| 멀티에서 차가 떨린다 | 물리 복제 + 서스펜션 | 클라이언트 로그 | 1.5절 모드 선택 |
| 아이템 300종 중 아이콘 누락 | 수동 관리 | AssetManager 검증 스크립트 | 빌드 전 자동 검증 |
| 셀 경계에서 히치 | 셀당 데이터 과다 | `open_world_helper.py grid` | 셀 분할 또는 에셋 경량화 |

---

## 11. 참고 자료

**건축 설계·치수**

- Ernst Neufert, *Architects' Data* — 건축 치수의 표준. 문·계단·가구·설비의 실측 치수 원천. 게임 스케일 변환의 기준값으로 쓴다.
- Francis D. K. Ching, *Architecture: Form, Space, and Order* — 매스·동선·비례·개구부의 시각 원리. 블록아웃 단계에서 가장 유용하다.
- Francis D. K. Ching, *A Visual Dictionary of Architecture* — 5장 용어의 그림 기준.
- Le Corbusier, *The Modulor* — 183 cm 인체 기준의 비례 체계(226/183/113/70/43). 게임 캐릭터 스케일 설계의 고전적 참조.
- Christopher Alexander, *A Pattern Language* — 공간 패턴(광장·문턱·창가)의 언어. POI·마을 설계에 직접 쓸 수 있다.
- Kevin Lynch, *The Image of the City* — 경로·경계·지구·결절점·랜드마크. 4.1절 길찾기 설계의 이론적 토대.
- 대한건축학회, *건축설계도면표현규칙* — 도면 기호·축척·치수의 국내 표준.

**언리얼 엔진**

- Chaos Vehicles: `UChaosWheeledVehicleMovementComponent`, `UChaosVehicleWheel`, `FChaosWheelSetup` API 레퍼런스.
- Networked Physics Overview(5.8) — Predictive Interpolation / Resimulation 모드의 동작과 비용.
- Modular Characters in Unreal Engine — 리더 포즈(Leader Pose) 기반 모듈러 캐릭터.
- Lumen Technical Details — 거리 필드·서피스 캐시와 누광 원인.
- Animation Budget Allocator, Significance Manager — 대량 캐릭터·소품의 틱 예산 관리.
- CitySample — MassTraffic/MassCrowd. 도시 규모 교통·군중의 레퍼런스 구현.

**함께 보는 저장소 문서**

- [open_world_creation_pipeline.md](open_world_creation_pipeline.md) — 월드 파티션·PCG·라이팅·HLOD의 기반.
- [pbr_material_pipeline.md](pbr_material_pipeline.md) — 텍스처·ORM·트림 시트 제작.
- [blender_pipeline.md](blender_pipeline.md) — 리토폴로지·베이킹·익스포트.
- [unreal_character_and_customization_guide.md](unreal_character_and_customization_guide.md) — 캐릭터·의상·외모 커스터마이징.
