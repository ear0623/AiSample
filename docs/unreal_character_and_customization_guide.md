# 언리얼 엔진 5 캐릭터 제작·커스터마이징 가이드 (C++)

> 대상: C++로 캐릭터 시스템을 직접 설계하는 개발자
> 범위: **Part 1** 플레이어 캐릭터(PC)와 논플레이어 캐릭터(NPC)의 차이와 제작 방법 → **Part 2** 모듈러 의상 시스템 → **Part 3** 외모(얼굴·체형·피부·헤어) 커스터마이징
> 기준 시점: **2026-11. Unreal Engine 5.8** 기준. 5.4 이후 권장되는 StateTree 등 버전 의존 항목은 본문에 버전을 적었다.
> 함께 쓰는 코드: [`examples/unreal_cpp_character/CharacterCustomizationTypes.h`](../examples/unreal_cpp_character/CharacterCustomizationTypes.h) · [`ModularCharacter.h`](../examples/unreal_cpp_character/ModularCharacter.h) · [`ModularCharacter.cpp`](../examples/unreal_cpp_character/ModularCharacter.cpp) · [`tests/test_cpp_examples.py`](../tests/test_cpp_examples.py)
> 함께 읽는 문서: [오픈월드 콘텐츠·건축 설계 매뉴얼](open_world_content_and_architecture_guide.md) · [오픈월드 제작 파이프라인](open_world_creation_pipeline.md) · [블렌더 파이프라인](blender_pipeline.md)

---

## 목차

**Part 1 — PC와 NPC**

0. [한눈에: 캐릭터는 세 층으로 나눈다](#0-한눈에-캐릭터는-세-층으로-나눈다)
1. [클래스 계층과 컨트롤러 분기](#1-클래스-계층과-컨트롤러-분기)
2. [대량 캐릭터의 성능 설계](#2-대량-캐릭터의-성능-설계)

**Part 2 — 모듈러 의상**

3. [모듈러 의상 시스템](#3-모듈러-의상-시스템)

**Part 3 — 외모 커스터마이징**

4. [외모 커스터마이징 시스템](#4-외모-커스터마이징-시스템)
5. [예제 코드와 검증](#5-예제-코드와-검증)
6. [체크리스트와 참고 자료](#6-체크리스트와-참고-자료)

---

## 0. 한눈에: 캐릭터는 세 층으로 나눈다

캐릭터 시스템이 커지면 반드시 섞이는 세 가지가 있다. 이 셋을 코드에서도 파일에서도 분리하면 대부분의 문제가 사라진다.

```
① 몸(Pawn)      ACharacter 파생. 이동·충돌·애니메이션 인스턴스·GAS 컴포넌트
                  PC든 NPC든 같은 몸을 쓴다. 차이는 "누가 조종하는가"뿐이다.
② 머리(Controller) APlayerController(입력·카메라) / AAIController(판단·경로)
                  몸은 컨트롤러를 모른다. 컨트롤러가 몸에 빙의(Possess)한다.
③ 입(입력)       Enhanced Input: IMC(맥락) + IA(행동). 걸을 때/차량에 탈 때/UI일 때
                  같은 IA를 다른 IMC로 재바인딩한다.
```

이 구조를 지키면 "NPC를 잠시 플레이어가 조종한다", "컷신에서 입력을 막는다", "차량에 탄다"가 모두 **컨트롤러/컨텍스트 교체**로 해결된다. 몸에 `if (bIsPlayer)`를 넣기 시작하면 그 순간부터 PC와 NPC가 갈라진다.

### 0.1 캐릭터 예산 (오픈월드·3인칭·60 fps 작성 예시)

| 구분 | PC(히어로) | 주요 NPC | 군중 NPC | 비고 |
| --- | --- | --- | --- | --- |
| 삼각형(LOD0) | 80k~150k | 30k~80k | 8k~15k | Nanite 스키닝은 5.5+에서 제한적, LOD 필수 |
| 본 수 | 120~250 | 80~150 | 40~70 | 얼굴 본은 히어로만 |
| 머티리얼 슬롯 | 4~8 (모듈러 합계) | 3~6 | 1~2 | 슬롯 = 드로우콜 |
| 텍스처 | 512 px/m | 256~512 | 128~256 | 피부·얼굴은 별도 2K |
| 모프 타깃 | 20~60 | 0~5 | 0 | 정점 델타 비용 |
| 클로스 메시 | 2~4 | 0~2 | 0 | 망토·치마 |
| 애니메이션 예산 | 1.5~3 ms | 2~5 ms (10명) | 0.5~1 ms (30명) | Budget Allocator로 배분 |
| 화면 동시 수 | 1~4 | 5~15 | 30~100 | |
| 네트워크 | 30~60 Hz | 10~20 Hz | 1~2 Hz | `NetUpdateFrequency` |

---

## 1. 클래스 계층과 컨트롤러 분기

### 1.1 계층 설계

```
APawn
 └ ACharacter                      (캡슐 + CharacterMovement + Mesh)
    └ ABaseCharacter               ← 공통: ASC, AttributeSet, Inventory, Interaction, 팀, 데미지
       ├ APlayerCharacter          ← 입력 바인딩, 카메라 리그, HUD 연계
       └ ANPCCharacter             ← AI 태그, 순찰 데이터, 대화 컴포넌트
```

`ABaseCharacter`에 넣을 것과 넣지 말 것:

| `ABaseCharacter`에 넣는다 | 넣지 않는다 |
| --- | --- |
| `UAbilitySystemComponent`(GAS) | 입력 바인딩(플레이어 전용) |
| `UAttributeSet`(체력·스태미나) | 카메라 컴포넌트(NPC는 불필요) |
| `UInventoryComponent` | `APlayerController` 캐스팅 |
| `IInteractableTarget` 구현(상호작용 주체) | 비헤이비어 트리 참조 |
| 팀·진영 태그, 데미지 처리 | UI 위젯 |
| 애니메이션 인스턴스 클래스 지정 | 특정 무기 로직 |

```cpp
// BaseCharacter.h (발췌)
UCLASS(Abstract)
class MYGAME_API ABaseCharacter : public ACharacter
{
    GENERATED_BODY()

public:
    explicit ABaseCharacter(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Character")
    TObjectPtr<UAbilitySystemComponent> AbilitySystemComponent;

    UPROPERTY()
    TObjectPtr<UMyAttributeSet> AttributeSet;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Character")
    TObjectPtr<UInventoryComponent> Inventory;

    /** 진영. GameplayTag로 두면 확장이 자유롭다. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Character")
    FGameplayTag TeamTag;

    virtual UAbilitySystemComponent* GetAbilitySystemComponent() const override;
};
```

생성자에서 GAS 컴포넌트를 만들 때 `SetIsReplicated(true)`와 `ReplicationMode`(플레이어는 `Mixed`, NPC는 `Minimal`)를 잊지 않는다. NPC에 `Full`을 쓰면 속성 복제 트래픽이 군중 수만큼 늘어난다.

### 1.2 이동·회전 규칙의 차이

PC와 NPC의 가장 실질적인 차이는 **누가 회전을 결정하는가**다.

| 설정 | PC(3인칭 액션) | PC(1인칭) | NPC |
| --- | --- | --- | --- |
| `bUseControllerRotationYaw` | false | true | false |
| `bOrientRotationToMovement` | true | false | true |
| `RotationRate` | (0, 500, 0) | — | (0, 240~360, 0) |
| `MaxWalkSpeed` | 600 (달리기) | 400 | 200~450 |
| `MaxAcceleration` | 2048 | 2048 | 1200~2048 |
| `BrakingDecelerationWalking` | 2048 | 2048 | 1200 |
| `bUseControllerDesiredRotation` | false | — | true (조준형 NPC) |
| `MaxStepHeight` | 45 | 45 | 45 |
| `WalkableFloorAngle` | 44.76 | 44.76 | 44.76 |
| `bRunPhysicsWithNoController` | false | false | — |

`bOrientRotationToMovement = true`면 캐릭터가 이동 방향으로 몸을 돌린다(액션 게임 표준). NPC의 `RotationRate`를 낮추면(240) 무거운 몸처럼, 높이면(540) 민첩하게 보인다. **이 회전 속도가 캐릭터의 성격을 만든다** — 좀비는 120, 산적은 360, 정예 기사는 300.

### 1.3 `APlayerController`: 입력과 카메라

#### Enhanced Input

```
UInputMappingContext (IMC)
  ├ IMC_OnFoot     : IA_Move, IA_Look, IA_Jump, IA_Interact, IA_Sprint
  ├ IMC_Vehicle    : IA_Throttle, IA_Steer, IA_Brake, IA_ExitVehicle
  └ IMC_UI         : IA_Navigate, IA_Confirm, IA_Cancel
```

컨텍스트는 **쌓인다.** 차량에 타면 `IMC_Vehicle`을 추가하고 `IMC_OnFoot`을 제거하지 않으면, 같은 키가 두 행동에 동시에 걸려 차가 서고 캐릭터가 뛴다. 전환은 다음처럼 명시적으로 한다.

```cpp
void APlayerCharacter::SetInputContext(EMyInputContext Context)
{
    if (!InputComponent || !PlayerController) { return; }

    UEnhancedInputLocalPlayerSubsystem* Subsystem =
        ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PlayerController->GetLocalPlayer());
    if (!Subsystem) { return; }

    // 이전 컨텍스트를 모두 제거한 뒤 새 컨텍스트만 추가한다(누수 방지).
    for (const TObjectPtr<UInputMappingContext>& Old : ActiveContexts)
    {
        if (Old) { Subsystem->RemoveMappingContext(Old); }
    }
    ActiveContexts.Reset();

    if (UInputMappingContext* NewContext = Contexts.FindRef(Context))
    {
        Subsystem->AddMappingContext(NewContext, /*Priority*/ 0);
        ActiveContexts.Add(NewContext);
    }
}
```

바인딩은 `UEnhancedInputComponent::BindAction`으로 하고, `Trigger`(Hold, Tap, Pressed)와 `Modifier`(Negate, Swizzle, DeadZone)를 **에셋 쪽에** 둔다. 코드에 `if (KeyHeldTime > 0.2)` 같은 시간 로직을 넣으면 에셋으로 조정할 수 없다.

```cpp
void APlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
    Super::SetupPlayerInputComponent(PlayerInputComponent);

    UEnhancedInputComponent* Input = CastChecked<UEnhancedInputComponent>(PlayerInputComponent);

    Input->BindAction(MoveAction, ETriggerEvent::Triggered, this, &APlayerCharacter::HandleMove);
    Input->BindAction(LookAction, ETriggerEvent::Triggered, this, &APlayerCharacter::HandleLook);
    Input->BindAction(JumpAction, ETriggerEvent::Started,  this, &ACharacter::Jump);
    Input->BindAction(JumpAction, ETriggerEvent::Completed, this, &ACharacter::StopJumping);
    Input->BindAction(SprintAction, ETriggerEvent::Started, this, &APlayerCharacter::StartSprint);
    Input->BindAction(SprintAction, ETriggerEvent::Completed, this, &APlayerCharacter::StopSprint);
}

void APlayerCharacter::HandleMove(const FInputActionValue& Value)
{
    const FVector2D Axis = Value.Get<FVector2D>();
    if (!Controller || Axis.IsNearlyZero()) { return; }

    // 카메라 기준(요 회전만 사용) → 월드 방향. 3인칭 액션의 표준.
    const FRotator YawRotation(0.f, Controller->GetControlRotation().Yaw, 0.f);
    const FVector Forward = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::X);
    const FVector Right   = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y);

    AddMovementInput(Forward, Axis.Y);
    AddMovementInput(Right, Axis.X);
}
```

#### 카메라

3인칭 카메라는 `USpringArmComponent` + `UCameraComponent` 조합이 표준이다.

| 설정 | 값 | 이유 |
| --- | --- | --- |
| `TargetArmLength` | 300~420 | 좁은 실내에서 420은 벽을 뚫는다 |
| `SocketOffset` | (0, 60, 80) | 어깨 너머 시점 |
| `bUsePawnControlRotation` | true | 마우스가 카메라를 돌린다 |
| `bEnableCameraLag` / `bEnableCameraRotationLag` | true / true | 0.1~0.2초. 없으면 이동이 딱딱하다 |
| `CameraLagSpeed` | 10~15 | |
| `bDoCollisionTest` | true | 벽 관통 방지 |
| `ProbeSize` | 12~18 | 너무 크면 문틀에서 카메라가 붙는다 |
| `CameraCollisionChannel` | `ECC_Camera` | 캐릭터·소품은 무시하고 벽만 |
| `FOV` | 90 (3인칭), 80~100 (달리기 시 +8) | 속도감 |

카메라 흔들림·FOV 변화는 `UCameraModifier` 파생 클래스로 만든다(무기에 넣지 않는다). 화면 효과가 무기 코드에 들어가면 무기를 바꿀 때 효과가 사라진다.

#### 입력 모드

| 상황 | 설정 |
| --- | --- |
| 게임플레이 | `FInputModeGameOnly` |
| 인벤토리·대화 | `FInputModeGameAndUI` + 마우스 커서 |
| 컷신·로딩 | `FInputModeUIOnly` 또는 입력 컨텍스트 제거 |

UI를 띄울 때 `GameAndUI`만 하고 `bShowMouseCursor`를 켜지 않으면 커서가 안 보이고, `GameOnly`로 두면 캐릭터가 계속 움직인다. 세트로 처리한다.

### 1.4 `AAIController`: 판단과 경로

NPC의 두뇌는 세 층으로 나뉜다.

```
[지각]      UAIPerceptionComponent(시야·청각) → Blackboard에 대상 기록
[판단]      Behavior Tree 또는 StateTree → 상태 전환, 목표 선택
[행동]      MoveTo / EQS / 상호작용 / 공격. 경로는 NavMesh + CrowdAvoidance
```

| 요소 | 언리얼 자산 | 역할 | 비고 |
| --- | --- | --- | --- |
| 지각 | `UAIPerceptionComponent` + `UAISenseConfig_Sight/Hearing` | 시야·청각 | `OnTargetPerceptionUpdated`로 반응 |
| 판단 | `UBehaviorTree` + `UBlackboardComponent` | 조건·시퀀스 | 전통적, 자료가 많다 |
| 판단 | `UStateTreeAIComponent`(5.4+ 권장) | 상태 기계 | 계층 상태·전이 조건이 명시적. 신규 프로젝트 권장 |
| 공간 질의 | `UEnvQueryManager`(EQS) | "엄폐할 곳", "순찰 지점" | 매 틱이 아니라 요청 시 |
| 경로 | `UNavigationSystemV1` + `ARecastNavMesh` | 길찾기 | 동적 장애물은 `Dynamic Modifiers` |
| 군중 회피 | `UCrowdFollowingComponent` | 서로 밀지 않고 비켜 감 | 20명 이상에서 필수 |
| 대량 | MassEntity / MassCrowd | 100명 이상 | 2장 |

StateTree를 쓸 때의 실무 이점: **전이 조건이 데이터로 보인다.** BT는 블랙보드 키와 데코레이터가 흩어져 "왜 이 상태로 갔는가"를 추적하기 어렵다. NPC 상태가 5개를 넘으면 StateTree로 옮기는 것이 유지보수에 유리하다.

```cpp
// NPCCharacter.cpp (발췌) — 스폰 시 AI 컨트롤러·행동 트리 지정
void ANPCCharacter::BeginPlay()
{
    Super::BeginPlay();

    if (AAIController* AI = Cast<AAIController>(GetController()))
    {
        if (BehaviorTree)
        {
            AI->RunBehaviorTree(BehaviorTree);
        }
    }
}

ANPCCharacter::ANPCCharacter(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    AIControllerClass = ANPCController::StaticClass();
    AutoPossessAI = EAutoPossessAI::PlacedInWorldOrSpawned;
}
```

`AutoPossessAI`를 설정하지 않으면 레벨에 배치한 NPC에 컨트롤러가 붙지 않는다(스폰 시에만 붙는 경우가 많다). `PlacedInWorldOrSpawned`가 안전한 기본값이다.

### 1.5 제작 파이프라인 차이

| 항목 | PC | 주요 NPC | 군중 NPC |
| --- | --- | --- | --- |
| 리깅 | 얼굴 본 + 손가락 + IK | 손가락 축약, 얼굴 없음 | 손·발 단순, 얼굴 텍스처 |
| 모프 타깃 | 얼굴 표정 30~60 | 0~5(체형) | 0 |
| 애니메이션 | 풀 세트(이동·전투·상호작용·표정) | 세트 축소(이동·전투·대화) | 이동 1~2개 + 랜덤 오프셋 |
| 애님 블루프린트 | 복잡(레이어·IK·본 보정) | 중간 | 단순 또는 Vertex Animation |
| LOD | 4~5단 | 3~4단 | 2~3단 |
| 클로스 | Chaos Cloth | 선택 | 없음 |
| 머티리얼 | 다층(피부·직물·금속) | 3~4 | 1~2 |
| 사운드 | 발소리·호흡·의상 | 발소리·대사 | 발소리 생략 또는 저비용 |

군중 NPC는 **Vertex Animation Texture(VAT)** 또는 `PoseableMesh` 대신 "스켈레탈 + 강한 LOD 축소"가 일반적이다. 100명 단위에서는 애니메이션 그래프 자체를 돌리지 않고, 미리 구운 애니메이션을 인스턴싱으로 재생하는 방식(MassCrowd)이 필요하다.

---

## 2. 대량 캐릭터의 성능 설계

오픈월드의 캐릭터 비용은 삼각형이 아니라 **애니메이션 평가 + 스킨 + 틱 + 복제**에서 나온다. 이 네 가지를 거리·중요도에 따라 줄이는 것이 2장의 전부다.

### 2.1 무엇이 비싼가

| 비용 | 측정 | 1명당(PC급) | 줄이는 수단 |
| --- | --- | --- | --- |
| 애니메이션 그래프 평가 | `stat anim` | 0.2~0.6 ms | Significance, Budget Allocator, URO |
| 스킨(스키닝) | `stat gpu` / skin cache | 0.1~0.3 ms | LOD, `r.SkinCache`, 원거리 단순 본 |
| 틱(블루프린트·컴포넌트) | `stat game` | 0.05~0.2 ms | `SetActorTickEnabled`, 틱 간격 |
| 복제 | `stat net` | 1~5 KB/s | `NetUpdateFrequency`, relevancy |
| 물리(클로스 포함) | `stat physics` | 0.2~0.8 ms | LOD에서 클로스 끄기 |
| 드로우콜 | `stat scenerendering` | 4~8 | 머티리얼 슬롯 축소, 병합 |

60 fps 예산 16.6 ms 중 캐릭터에 4~5 ms를 배분한다면, PC 1명(2~3 ms)과 NPC 10명(2~3 ms)이 한계다. 20명 이상이면 2.2~2.4절의 감축이 필수다.

### 2.2 Significance Manager

거리·화면 점유율로 액터의 "중요도"를 계산해 틱·애니메이션·이펙트를 단계적으로 줄인다.

```
[Spawn]  RegisterObject(Actor, Info, SignificanceFunction, PostSignificanceFunction)
[Tick]   엔진이 주기적으로 SignificanceFunction 호출 → 0.0~1.0 반환
[적용]   PostSignificanceFunction(Significance)에서 틱 간격·애니메이션 모드·이펙트 토글
```

| 중요도 | 거리(예시) | 적용 |
| --- | --- | --- |
| 1.0 | 0~10 m | 풀 애니메이션, 클로스, 얼굴 모프 |
| 0.6~1.0 | 10~30 m | 애니메이션, 클로스 끔 |
| 0.3~0.6 | 30~60 m | 틱 2프레임에 1회, LOD2 |
| 0.1~0.3 | 60~120 m | 애니메이션 4프레임에 1회, LOD3 |
| 0.0 | 120 m+ | 애니메이션 정지(포즈 고정), 컬 |

`SignificanceManager`는 플러그인이 아니라 엔진 서브시스템(`USignificanceManager`)이며 `DefaultGame.ini`의 `[/Script/SignificanceManager.SignificanceManager]`에 관리 클래스·거리 설정을 둔다. Lyra가 이 구조의 레퍼런스다.

### 2.3 Animation Budget Allocator

애니메이션에 **고정 밀리초 예산**을 주고, 초과하면 중요도가 낮은 메시의 업데이트 주기를 늘리거나 보간을 끈다. 개별 최적화보다 훨씬 예측 가능하다.

| 항목 | 설정 | 기본값 |
| --- | --- | --- |
| 컴포넌트 클래스 | `USkeletalMeshComponentBudgeted` | `bAutoRegisterWithBudgetAllocator = true` |
| 중요도 자동 계산 | `bAutoCalculateSignificance` | true |
| 예산 | `a.Budget.BudgetMs` | 1.0 ms (플랫폼별 조정) |
| 디버그 | `a.Budget.Debug.Enabled 1` | 화면에 예산 그래프 |
| 강제 적용 | `a.Budget.Debug.Force 1` | 낮은 예산에서 동작 확인 |

플랫폼별 예산은 `DefaultScalability.ini`에 둔다.

```ini
[ViewDistanceQuality@0]
a.Budget.BudgetMs=1.0

[ViewDistanceQuality@3]
a.Budget.BudgetMs=2.5
```

C++에서 컴포넌트 클래스를 바꾸려면 생성자에서 기본 서브오브젝트 클래스를 교체한다.

```cpp
AMyNPC::AMyNPC(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer.SetDefaultSubobjectClass<USkeletalMeshComponentBudgeted>(ACharacter::MeshComponentName))
{
}
```

Budget Allocator는 **리더 포즈 컴포넌트를 우대**한다(3장). 모듈러 캐릭터가 유리한 이유 중 하나다.

### 2.4 Update Rate Optimization와 틱 간격

| 기능 | 설정 | 효과 |
| --- | --- | --- |
| URO | `Mesh->bEnableUpdateRateOptimizations = true` | 카메라 밖/원거리에서 애니메이션 갱신 주기 자동 증가 |
| 강제 LOD | `Mesh->SetForcedLodModel(n)` | 테스트·연출용 |
| 가시성 기반 포즈 틱 | `Mesh->VisibilityBasedAnimTickOption` | `OnlyTickPoseWhenRendered`(기본) / `AlwaysTickPoseAndRefreshBones` |
| 액터 틱 | `SetActorTickEnabled(false)` + 타이머 | 원거리에서 완전 정지 |
| 틱 간격 | `SetActorTickInterval(0.1f)` | 100 ms 간격이면 10명이 1명 비용 |
| 복제 빈도 | `NetUpdateFrequency = 5` | 원거리 NPC |
| 컬 거리 | `NetCullDistanceSquared` | 복제 자체를 끊는다 |

주의: `OnlyTickPoseWhenRendered`는 **화면에 없으면 포즈가 갱신되지 않는다.** 화면 밖에서 애니메이션이 진행되어야 하는 경우(예: 화면 밖 저격수의 조준)에는 개별 예외를 둔다.

### 2.5 LOD별 감축 표

| LOD | 화면 점유 | 애니메이션 | 클로스 | 얼굴 모프 | 드로우콜 |
| --- | --- | --- | --- | --- | --- |
| 0 | 100 % | 풀 | 켬 | 켬 | 4~8 |
| 1 | 50 % | 풀 | 켬 | 끔 | 3~6 |
| 2 | 25 % | 2프레임당 | 끔 | 끔 | 2~4 |
| 3 | 10 % | 4프레임당 | 끔 | 끔 | 1~2 |
| 4(군중) | 3 % | 정지 또는 VAT | 끔 | 끔 | 1 |

이 표를 애니메이션 블루프린트의 `LOD` 노드가 아니라 **C++에서 일괄 적용**하는 것이 좋다. 컴포넌트가 LOD를 바꿀 때 델리게이트(`OnLODChanged` 계열)나 `USkinnedMeshComponent::UpdateLODStatus` 훅에서 일괄 처리하고, 아티스트가 LOD마다 잊어버릴 여지를 없앤다.

---

## 3. 모듈러 의상 시스템

### 3.1 슬롯 설계

캐릭터를 "몸 + 부위별 메시"로 나누는 방식은 한 벌의 완성된 메시를 교체하는 방식보다 제작·조합 비용이 압도적으로 낮다. 슬롯은 게임의 장비 부위와 1:1로 맞춘다.

| 슬롯 | 메시 예산(삼각형) | 마스킹 대상(몸) | 비고 |
| --- | --- | --- | --- |
| `Head` (모자·투구) | 2k~15k | 머리 윗부분 | 얼굴 노출 여부가 게임플레이에 영향 |
| `Torso` (상의·갑옷) | 10k~40k | 몸통·팔 | 가장 비싼 슬롯 |
| `Legs` (하의) | 6k~25k | 골반·허벅지 | 치마형은 클로스 |
| `Feet` (신발) | 2k~8k | 발·발목 | |
| `Hands` (장갑) | 1k~5k | 손 | 손가락 본을 공유해야 함 |
| `Back` (망토·배낭) | 2k~12k | 없음 | 클로스 또는 강체 |

설계 규칙 네 가지.

1. **모든 슬롯 메시는 같은 스켈레톤을 공유한다.** 본 이름·계층이 다르면 리더 포즈가 성립하지 않는다(스킨 웨이트는 달라도 된다).
2. **LOD 개수를 맞춘다.** 상의가 LOD 4단인데 신발이 2단이면, 상의 LOD3에서 신발은 LOD1로 남아 화면에서 신발만 고밀도가 된다.
3. **바운즈를 명시한다.** 팔로어 메시는 자체 바운즈가 작아 화면 가장자리에서 먼저 컬된다. `bUseAttachParentBound = true` 또는 리더 바운즈에 병합한다.
4. **숨김 처리는 슬롯에 맡긴다.** "이 상의는 몸통을 가린다"를 메시가 아니라 데이터(`bHideBodyUnderneath`)로 둔다(3.6).

### 3.2 리더 포즈(Leader Pose)의 원리와 제약

`USkeletalMeshComponent::SetLeaderPoseComponent(Leader, bForceUpdate, bInFollowerShouldTickPose)`는 팔로어 컴포넌트가 **자기 애니메이션을 평가하지 않고 리더의 컴포넌트 공간 본 트랜스폼을 그대로 사용**하게 한다.

```
[리더: 몸]  애니메이션 그래프 평가 → 본 트랜스폼 계산 → 스킨 → 렌더
     │  (컴포넌트 공간 본 트랜스폼 공유)
     ├─▶ [팔로어: 상의]  애니메이션 평가 생략 → 스킨만 → 렌더
     ├─▶ [팔로어: 하의]  애니메이션 평가 생략 → 스킨만 → 렌더
     └─▶ [팔로어: 신발]  애니메이션 평가 생략 → 스킨만 → 렌더
```

이득: 애니메이션 그래프 평가 비용이 **부위 수와 무관하게 1회**. 6부위 캐릭터라도 비용은 몸 1개 + 스킨 6회다. 손실: 팔로어는 자기 애니메이션을 못 가진다(망토 흔들림을 별도 애니메이션으로 만들 수 없다 — 클로스나 별도 본으로 해결).

#### 제약과 함정 (실무에서 실제로 물리는 것들)

| 함정 | 실제 동작 | 대응 |
| --- | --- | --- |
| **모프 타깃이 안 따라온다** | 리더의 커브 중 **morph 커브와 material 커브만** 팔로어로 복사된다. `SetMorphTarget`으로 직접 넣은 값은 팔로어 커브 컨테이너에서 **매 프레임 초기화**된다 | ① 모프를 애님 커브(`ModifyCurve`)로 구동하고 스켈레톤에 morph target curve를 등록 ② 또는 팔로어에 매 프레임 `SetMorphTarget` 재적용(예제 코드의 `bRefreshFollowerMorphs`) |
| 생성자/`OnConstruction`에서 설정 | `SetMorphTarget`은 `UnsafeDuringActorConstruction`이다. 생성 중 호출은 신뢰할 수 없다 | `BeginPlay` 이후에 설정. 에디터 뷰포트 미리보기는 별도 처리 필요 |
| LOD가 따로 논다 | 팔로어 LOD는 자기 화면 크기로 계산된다 | `bSyncAttachParentLOD = true` |
| 화면 가장자리에서 옷만 사라진다 | 팔로어 바운즈가 작다 | `bUseAttachParentBound = true`, 또는 `SetCullDistance` 통일 |
| 그림자가 2중으로 진다 | 몸과 옷이 모두 그림자를 만든다 | 옷 아래 몸은 `bCastHiddenShadow = false`, `bAffectDynamicIndirectLighting` 조정 |
| 소유자에게 몸이 보인다 | 1인칭에서 자기 몸 | `bOwnerNoSee`(팔로어), `bOnlyOwnerSee`(팔) |
| 팔로어의 소켓이 어긋난다 | 소켓은 팔로어 스켈레톤 기준으로 평가된다 | 무기·소품 소켓은 **리더(몸) 메시**에만 둔다 |
| 팔로어의 물리 에셋이 폭발 | 팔로어가 자체 물리 상태를 만든다 | 팔로어는 `SetSimulatePhysics(false)`, 물리 에셋 미지정. 레그돌은 리더만 |
| 클로스가 안 움직인다 | `bInFollowerShouldTickPose=false`면 팔로어 틱이 꺼진다 | 클로스는 컴포넌트 틱이 필요 → 클로스 팔로어는 `bInFollowerShouldTickPose=true` 또는 별도 처리 |

마지막 항목이 특히 중요하다. 클로스가 있는 팔로어(망토·치마)는 애니메이션 평가는 생략해도 **클로스 시뮬레이션 틱은 필요**하다. `SetLeaderPoseComponent(Leader, false, /*bInFollowerShouldTickPose*/ true)`로 두고, 애니메이션 예산은 Budget Allocator에 맡긴다.

### 3.3 분리 컴포넌트 vs 런타임 병합

| 항목 | 분리 컴포넌트 + 리더 포즈 | 런타임 병합(`USkeletalMergingLibrary::MergeMeshes`) |
| --- | --- | --- |
| 애니메이션 평가 | 1회(리더만) | 1회 |
| 스킨 비용 | 부위 수만큼 | 1회(정점 수 동일) |
| 드로우콜 | 부위 × 머티리얼 슬롯 | 1~2 (아틀라스 시) |
| 런타임 교체 | 즉시, 자유롭게 | 메시 재생성 필요(수 ms~수십 ms 히치) |
| 메모리 | 원본 메시 공유(좋다) | 새 `USkeletalMesh` 인스턴스(나쁘다, 부위별 조합마다) |
| 클로스 | 팔로어별로 정상 동작 | **병합 시 클로스가 사라진다**(`BindToSkeletalMesh` 별도 작업 필요) |
| 모프 타깃 | 팔로어별 처리 필요 | 병합 시 모프가 유지되지 않음 |
| LOD | 컴포넌트별 | 병합 시 LOD 재생성 |
| 적합한 곳 | 플레이어·주요 NPC(교체 잦음) | 군중 NPC, 원거리 LOD, 모바일(드로우콜 민감) |

병합은 "조합이 고정된 캐릭터"에만 쓴다. 플레이어 캐릭터처럼 장비를 수시로 바꾸는 대상에는 맞지 않는다. 병합 API는 엔진의 **Skeletal Merging 모듈**을 프로젝트에 추가해야 한다.

```cpp
// 런타임 병합 (군중 NPC 등 조합이 고정된 경우)
#include "SkeletalMergingLibrary.h"

USkeletalMesh* UMyCharacterAssembler::MergeParts(const TArray<USkeletalMesh*>& Parts, USkeleton* Skeleton)
{
    if (Parts.Num() < 2 || !Skeleton) { return nullptr; }

    FSkeletalMeshMergeParams Params;
    Params.MeshesToMerge = Parts;
    Params.Skeleton = Skeleton;
    Params.StripTopLODS = 0;
    Params.bNeedsCpuAccess = false;      // CPU 접근이 필요 없으면 false(메모리 절약)
    Params.bSkeletonBefore = true;

    return USkeletalMergingLibrary::MergeMeshes(Params);
}
```

### 3.4 장착 흐름

```
EquipMesh(Slot, SoftMesh, bHideBody)
   │
   ├─① 상태 갱신        FClothingSlotState 갱신, Customization.Slots에 반영(서버 권위)
   ├─② 비동기 로드      StreamableManager.RequestAsyncLoad(Mesh.ToSoftObjectPath(), Delegate)
   │                     └─ 완료 콜백에서 ③~⑦ 실행 (로드 실패 시 이전 메시 유지)
   ├─③ 메시 교체        Comp->SetSkeletalMesh(Loaded)
   ├─④ 리더 포즈        Comp->SetLeaderPoseComponent(GetMesh(), false, bNeedsTick)
   ├─⑤ LOD/바운즈       bSyncAttachParentLOD, bUseAttachParentBound, 컬 거리
   ├─⑥ 색·파라미터      CreateDynamicMaterialInstance → SetVectorParameterValue
   ├─⑦ 모프·마스킹      ApplyMorphTargets(), UpdateBodyMask()
   └─⑧ 외형 통지        OnCustomizationChanged 델리게이트(UI·세이브·통계)
```

비동기 로드를 **반드시** 쓰는 이유: 장비 교체는 UI에서 자주 일어나고, 오픈월드에서는 그 시점에 다른 스트리밍도 진행 중이다. 동기 로드는 수십 ms 히치로 나타난다.

```cpp
void AModularCharacter::EquipMesh(EClothingSlot Slot, TSoftObjectPtr<USkeletalMesh> Mesh, bool bHideBodyUnderneath)
{
    if (!CanModifyCustomization()) { return; }

    FClothingSlotState& State = GetOrAddSlotState(Slot);
    State.Slot = Slot;
    State.ResolvedMesh = Mesh;
    State.bHideBodyUnderneath = bHideBodyUnderneath;

    USkeletalMeshComponent* Comp = GetMeshForSlot(Slot);
    if (!Comp || Mesh.IsNull())
    {
        ClearSlot(Slot);
        return;
    }

    if (USkeletalMesh* AlreadyLoaded = Mesh.Get())
    {
        ApplySlotMesh(Slot, AlreadyLoaded);       // 이미 로드됨(대부분의 경우)
        return;
    }

    // 아직 로드되지 않았다면 비동기 로드 후 적용한다.
    const FSoftObjectPath Path = Mesh.ToSoftObjectPath();
    PendingLoads.Add(Slot, Path);

    const FStreamableDelegate Delegate = FStreamableDelegate::CreateUObject(
        this, &AModularCharacter::OnSlotMeshLoaded, Slot, Path);

    UAssetManager::GetStreamableManager().RequestAsyncLoad(Path, Delegate, FStreamableManager::AsyncLoadHighPriority);
}

void AModularCharacter::OnSlotMeshLoaded(EClothingSlot Slot, FSoftObjectPath Path)
{
    // 로드 중 다른 장비로 바뀌었으면 결과를 버린다(경쟁 조건 방지).
    if (PendingLoads.FindRef(Slot) != Path) { return; }

    if (USkeletalMesh* Loaded = Cast<USkeletalMesh>(Path.ResolveObject()))
    {
        ApplySlotMesh(Slot, Loaded);
    }
}
```

요점은 마지막의 **경쟁 조건 검사**다. 플레이어가 빠르게 장비를 바꾸면 이전 요청의 콜백이 나중에 도착해 엉뚱한 메시를 입힌다. 슬롯별로 "마지막 요청 경로"를 기록하고 다르면 폐기한다.

### 3.5 클로스(Chaos Cloth)

| 항목 | 값/설정 | 비고 |
| --- | --- | --- |
| 시뮬레이션 활성 | `Mesh->bDisableClothSimulation = false` | 원거리 LOD에서 true |
| 서브디비전 | `SubdivisionCount` 0~3 | 1이 기본, 망토는 1~2. 3은 비용 4~9배 |
| 솔버 주기 | `SolverFrequency`(보통 60~120 Hz) | 낮으면 떨림 |
| 충돌 두께 | `CollisionThickness` 2~5 cm | 얇으면 몸을 뚫고, 두꺼우면 옷이 붕 뜬다 |
| 자체 충돌 | `bUseSelfCollisions` + `SelfCollisionThickness` | 망토 필수. 비용 2~3배 |
| 감쇠 | `DampingCoefficient` | 바람에 펄럭이는 연출과 직결 |
| 중력/바람 | `Gravity`, `WindVelocity` | 런타임에 날씨와 연동 |

C++ 런타임 제어는 `UClothingSimulationInteractor`(구현체 `UChaosClothingInteractor`)의 패널 API로 한다. 에셋을 다시 임포트하지 않고 실행 중에 값을 바꿀 수 있다.

```cpp
#include "Components/SkeletalMeshComponent.h"
// UClothingSimulationInteractor는 ClothingSystemRuntimeInterface 모듈,
// UChaosClothingInteractor는 Chaos 계열 모듈에 있다. Build.cs에 추가한다.

void AModularCharacter::ApplyCloakEnvironment(float WindSpeed, bool bEnableSimulation)
{
    USkeletalMeshComponent* MeshComp = GetMeshForSlot(EClothingSlot::Back);
    if (!MeshComp) { return; }

    // 가장 싼 감축: 시뮬레이션을 끄고(메시는 유지) LOD 전환 시점에 호출한다.
    MeshComp->bDisableClothSimulation = !bEnableSimulation;
    if (!bEnableSimulation) { return; }

    // 범용 인터랙터: 시뮬레이션 영향 반경을 조절한다(0이면 사실상 정지).
    if (UClothingSimulationInteractor* Interactor = MeshComp->GetClothingSimulationInteractor())
    {
        Interactor->SetClothMaxDistanceScale(1.f);
    }

    // 바람·감쇠는 Chaos 구현체의 패널 API로 조정한다(Chaos 모듈 의존).
    //   UChaosClothingInteractor* Chaos = Cast<UChaosClothingInteractor>(Interactor);
    //   Chaos->SetWindVelocity(FVector(WindSpeed, 0.f, 0.f));
    //   Chaos->SetDamping(FVector2D(1.2f, 1.2f));
}
```

거리별 감축은 `SetClothMaxDistanceScale(0)`으로 클로스를 "정지"시키는 방법이 가장 싸다(시뮬레이션 중단, 메시는 유지). LOD 2 이상에서 끄고, 화면에 다시 들어오면 한 프레임 동안 블렌드해 복원한다.

### 3.6 클리핑(메시 관통) 해결

옷이 몸을 뚫는 문제는 반드시 생긴다. 원인은 ① 스킨 웨이트 차이 ② 모프 타깃 미적용 ③ 체형 스케일 차이 ④ 포즈 한계(팔을 90° 이상 들 때)다. 한 가지 방법으로는 못 막고, **네 단계 방어선**을 둔다.

| 단계 | 방법 | 해상도 | 비용 | 단점 |
| --- | --- | --- | --- | --- |
| ① 스킨 규약 | 옷의 스킨 웨이트 = 몸의 스킨 웨이트(몸 메시에서 전사) | 정점 | 없음 | 제작 공정 필요 |
| ② 마스킹 머티리얼 | 몸의 가려지는 영역을 UV2/버텍스 알파 마스크로 알파 컷 | 텍셀(0.5~2 cm) | 마스크 텍스처 1장, 마스킹 셰이더 | 가려진 부위도 스킨·그림자 비용은 남는다 |
| ③ 본 숨기기 | `HideBoneByName`으로 몸의 특정 본 영역 폴리곤 제거 | 본 단위(굵다) | 거의 없음 | 경계가 부자연스럽다 |
| ④ 지오메트리 제거 | "옷 입은 몸" 전용 LOD(몸통·팔 제거) | 정점 | 없음(오히려 절약) | 교체 시 메시 스왑 필요 |

실무 조합: **①+②가 기본**, 근접 히어로는 **④**, 원거리·군중은 **②만**.

```cpp
// 몸의 마스킹 머티리얼에 "이 부위는 가려졌다"를 스칼라 파라미터로 알린다.
void AModularCharacter::UpdateBodyMask()
{
    USkeletalMeshComponent* Body = GetMesh();
    if (!Body || !Body->GetSkeletalMeshAsset()) { return; }

    UEnum* SlotEnum = StaticEnum<EClothingSlot>();
    for (int32 SlotIndex = 0; SlotIndex < static_cast<int32>(EClothingSlot::Count); ++SlotIndex)
    {
        const EClothingSlot Slot = static_cast<EClothingSlot>(SlotIndex);
        const FClothingSlotState* State = Customization.FindSlot(Slot);
        const bool bCovered = State && State->bHideBodyUnderneath && !State->ResolvedMesh.IsNull();

        const FName ParameterName(*FString::Printf(TEXT("Coverage_%s"),
            *SlotEnum->GetNameStringByValue(SlotIndex)));

        for (int32 MaterialIndex = 0; MaterialIndex < Body->GetNumMaterials(); ++MaterialIndex)
        {
            if (UMaterialInstanceDynamic* MID = GetOrCreateSlotMID(Body, MaterialIndex))
            {
                MID->SetScalarParameterValue(ParameterName, bCovered ? 1.f : 0.f);
            }
        }
    }
}
```

본 단위 숨김은 마스킹이 불가능한 곳(손가락·발목)에만 쓴다.

```cpp
// 예: 신발을 신으면 발목 아래 본 영역을 제거
Body->HideBoneByName(TEXT("foot_l"), EPhysBodyOp::PBO_None);
```

`HideBoneByName`은 **렌더링 폴리곤만 제거**하고 스켈레톤·물리는 유지한다. 다시 보이게 하려면 `ShowAllBones()` 또는 `UnHideBoneByName()`이다.

### 3.7 무기·소품 부착

| 대상 | 부착 위치 | 규칙 |
| --- | --- | --- |
| 무기 | 리더 메시의 손 소켓(`Weapon_R`) | 팔로어 소켓은 쓰지 않는다 |
| 방패 | 팔 소켓 | |
| 등 장비(검집·배낭) | 등 소켓(`Spine_02`) | Back 슬롯 메시와 겹치지 않게 오프셋 |
| 소품(랜턴·컵) | 손 소켓 + 별도 오프셋 | 캐릭터가 아닌 소품 액터가 부착 |

```cpp
void AMyCharacter::AttachWeapon(AActor* WeaponActor, FName SocketName)
{
    if (!WeaponActor || !GetMesh()) { return; }

    WeaponActor->AttachToComponent(
        GetMesh(),
        FAttachmentTransformRules::SnapToTargetNotIncludingScale,
        SocketName);
}
```

방어 코드: 소켓 이름이 없으면 `AttachToComponent`는 조용히 실패하고 액터가 월드 원점에 남는다. `GetMesh()->DoesSocketExist(SocketName)`을 먼저 검사하고 실패 시 로그를 남긴다.

---

## 4. 외모 커스터마이징 시스템

### 4.1 파라미터 축

커스터마이징 UI를 만들기 전에 **파라미터를 축으로 정리**한다. 축이 정리되면 UI·데이터·직렬화·복제가 모두 같은 구조를 쓴다.

| 축 | 파라미터 | 표현 수단 | 비용 | 복제 크기 |
| --- | --- | --- | --- | --- |
| 얼굴 형태 | 눈·코·입·턱 20~40종 | 모프 타깃 | 정점 델타 | 1종당 1바이트(0~255) |
| 체형 | 키·어깨·허리·다리 길이 | 본 스케일 + 모프 | 낮음 | 축당 1바이트 |
| 피부 | 색조·주근깨·흉터·문신 | MID 색 + 마스크 텍스처 | 텍스처 1~3장 | 색 3~4바이트, 마스크 인덱스 1바이트 |
| 헤어 | 스타일·색·길이 | Groom/카드 메시 + MID 색 | 메시·본 비용 | 스타일 ID + 색 3~4바이트 |
| 눈 | 색·동공 | MID 색 | 없음 | 4바이트 |
| 의상 | 슬롯별 아이템 + 색 | 메시 + MID | 3장 | 슬롯당 ID 2바이트 + 색 |

원칙: **"연속값은 모프/스케일, 이산값은 ID"**. 얼굴 형태는 연속(0~1), 헤어 스타일은 이산(에셋 ID)이다. 둘을 같은 배열에 섞으면 UI도 직렬화도 지저분해진다.

### 4.2 모프 타깃(Morph Target / Blend Shape)

#### 동작 원리

모프 타깃은 "정점 위치 델타의 집합"이다. GPU 스킨 단계 이전(또는 정점 셰이더)에서 `최종 위치 = 기본 위치 + Σ(델타_i × 가중치_i)`로 적용된다.

- **합산**된다. 여러 모프가 같은 정점을 움직이면 더해진다. 그래서 "코 크게 + 눈 작게" 같은 조합이 자연스럽게 섞인다.
- **노멀은 자동 재계산되지 않는다.** 큰 모프(얼굴 윤곽)는 노멀이 어긋나 조명이 이상해진다. 임포트 시 "Import Normals" 옵션이나 별도 노멀 델타가 필요하다.
- **비용은 정점 수 × 활성 모프 수**다. 얼굴 메시 15k 정점에 모프 30개가 모두 0이 아니면 무겁다. 실무에서는 동시에 4~8개만 0이 아니게 설계한다.

| API | 용도 |
| --- | --- |
| `SetMorphTarget(FName Name, float Value, bool bRemoveZeroWeight = true)` | 가중치 설정 |
| `ClearMorphTargets()` | 전체 초기화(프리셋 전환 시) |
| `GetNumMaterials` / `GetSkeletalMeshAsset()->GetMorphTargets()` | 유효 이름 검증 |
| `bDisableMorphTarget` | 성능 옵션(모프 전체 끄기) |

```cpp
void AModularCharacter::ApplyMorphTargets()
{
    USkeletalMeshComponent* Body = GetMesh();
    if (!Body) { return; }

    // 1) 몸에 적용
    for (const FCharacterMorphTarget& Morph : Customization.MorphTargets)
    {
        if (Morph.Name.IsNone()) { continue; }
        Body->SetMorphTarget(Morph.Name, FMath::Clamp(Morph.Weight, 0.f, 1.f));
    }

    // 2) 팔로어(옷)에도 같은 모프를 적용한다.
    //    리더 포즈 팔로어의 모프 커브 컨테이너는 매 프레임 초기화되므로,
    //    bRefreshFollowerMorphs가 켜져 있으면 Tick에서 재적용한다(3.2절).
    if (bRefreshFollowerMorphs)
    {
        RefreshFollowerMorphs();
    }
}
```

#### 모프와 리더 포즈

3.2절에서 본 제약이 여기서 결정적이다. 옷이 몸의 모프(체형)를 따라 늘어나려면 옷 메시에도 **같은 이름의 모프 타깃**이 있어야 한다. 그리고 그 값을 리더에서 팔로어로 전달하는 방법은 두 가지뿐이다.

| 방법 | 구현 | 장점 | 단점 |
| --- | --- | --- | --- |
| **애님 커브** | 몸 AnimBP에서 `ModifyCurve`로 morph 커브 값 설정 → 엔진이 팔로어에 복사 | 프레임당 비용 1회 | 스켈레톤에 morph target curve 등록 필요, C++만으로는 제어가 간접적 |
| **팔로어 직접 설정** | 코드에서 팔로어마다 `SetMorphTarget` 매 프레임 | 단순, 즉시 반영 | 팔로어 수 × 모프 수 호출, 커브 컨테이너 갱신 비용 |

프로덕션 권장: **체형 모프(항상 켜져 있음)는 애님 커브**, **표정 모프(일시적)는 리더만**. 옷이 따라가야 하는 것은 체형뿐이므로, 체형 모프만 커브로 돌리면 팔로어 부담이 거의 없다.

### 4.3 체형: 본 스케일링

키·다리 길이·어깨 폭처럼 "골격 자체"를 바꾸는 값은 모프보다 본 스케일이 적합하다. 옷과 무기 소켓이 자동으로 따라오기 때문이다.

```
AnimBP의 Post Process 노드에 Modify Bone 노드 추가
  Bone: thigh_l / thigh_r       (또는 pelvis, spine_01 등)
  Translation Mode: Additive
  Scale: (WidthScale, WidthScale, LengthScale)
  Space: Bone Space
```

```cpp
// AnimInstance에 노출한 변수를 캐릭터가 설정한다.
void UMyAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
    Super::NativeUpdateAnimation(DeltaSeconds);

    if (const AModularCharacter* Character = Cast<AModularCharacter>(TryGetPawnOwner()))
    {
        // Modify Bone 노드가 이 값을 읽어 thigh 본의 스케일을 바꾼다.
        LegLengthScale = Character->GetCustomization().LegLengthScale;
        ShoulderWidthScale = Character->GetCustomization().ShoulderWidthScale;
    }
}
```

주의 사항:

| 문제 | 대응 |
| --- | --- |
| 캡슐이 안 커진다 | `GetCapsuleComponent()->SetCapsuleSize(Radius * Scale, HalfHeight * Scale)`를 함께 호출. 카메라·스프링암 위치도 보정 |
| 발이 땅에 박히거나 뜬다 | 발 IK(Foot IK)를 켜고 `Pelvis` 높이를 보정. 스케일 변경 후 1프레임은 IK가 적응하지 못한다 |
| 옷이 늘어나며 클리핑 | 옷도 같은 본을 쓰므로 자동으로 늘어난다. 클리핑은 마스킹(3.6)으로 |
| 무기 소켓 위치가 어긋난다 | 소켓은 본에 붙어 있으므로 자동으로 따라온다. 문제가 생기면 소켓 상대 트랜스폼이 스케일을 상속하지 않게 설정 |
| 물리 에셋이 깨진다 | 본 스케일은 물리 바디에 반영되지 않는다. 레그돌 시 스케일을 1로 복원 |

### 4.4 피부·머리·문신: 동적 머티리얼 인스턴스

`UMaterialInstanceDynamic`(MID)은 런타임에 파라미터를 바꾸는 유일한 정식 경로다. 캐릭터마다 MID를 만들면 머티리얼 인스턴싱이 깨져 드로우콜이 늘어난다. 그래서 **MID 수를 예산으로 관리**한다.

| 대상 | MID 수(권장) | 비고 |
| --- | --- | --- |
| 피부 | 1 | 색조·SSS·문신 마스크를 파라미터로 |
| 머리 | 1 | 색·광택 |
| 눈 | 1 | 홍채 색 |
| 의상 | 슬롯당 1~2 | 메시가 여러 머티리얼 슬롯이면 그만큼 |
| 액세서리 | 0 (원본 MI 공유) | 색 변화가 없으면 MID 만들지 않는다 |
| **합계** | **6~10** | 캐릭터 1명당. 20명이면 120~200 MID |

```cpp
void AModularCharacter::ApplySkinParameters(const FCharacterCustomizationData& Data)
{
    USkeletalMeshComponent* Body = GetMesh();
    if (!Body) { return; }

    for (int32 MaterialIndex = 0; MaterialIndex < Body->GetNumMaterials(); ++MaterialIndex)
    {
        UMaterialInstanceDynamic* MID = GetOrCreateSlotMID(Body, MaterialIndex);
        if (!MID) { continue; }

        MID->SetVectorParameterValue(TEXT("SkinTint"), Data.SkinTint.Value);
        MID->SetScalarParameterValue(TEXT("FreckleAmount"), Data.FreckleAmount);
        MID->SetScalarParameterValue(TEXT("ScarAmount"), Data.ScarAmount);

        if (!Data.TattooMask.IsNull())
        {
            // 텍스처 파라미터는 로드된 UTexture만 넣는다(스트리밍 중 null 주의).
            if (UTexture* Tattoo = Data.TattooMask.LoadSynchronous())
            {
                MID->SetTextureParameterValue(TEXT("TattooMask"), Tattoo);
            }
        }
    }
}
```

머티리얼 설계 측:

| 파라미터 | 타입 | 역할 |
| --- | --- | --- |
| `SkinTint` | Vector | 피부 색조. 베이스 텍스처에 곱 |
| `Subsurface Profile` | 머티리얼 에셋 설정 | 피부 산란. 색조마다 프로필을 바꾸면 비용이 크므로 2~3개 공유 |
| `FreckleAmount` / `ScarAmount` | Scalar | 마스크 텍스처 강도 |
| `TattooMask` | Texture | 문신 레이어(별도 UV 세트 권장) |
| `RoughnessOffset` | Scalar | 화장·노화 표현 |
| `MakeupMask` | Texture | 입술·눈가 색 |

라이팅 참고: 피부는 **서브서피스 프로파일(Subsurface Profile)** 셰이딩 모델이 있어야 Lumen 환경에서 살아 보인다. 기본 `Subsurface` 모드는 산란 반경을 머티리얼마다 지정해야 하고 색이 죽는다.

### 4.5 헤어: Groom(스트랜드) vs 카드(Hair Cards)

| 항목 | Groom(스트랜드) | 카드(Cards) |
| --- | --- | --- |
| 표현 | 실제 가닥 수천~수만 | 평면 20~80장 + 알파 |
| 비용 | 스킨·시뮬·정렬 비용 큼(수 ms) | 낮음(0.1~0.5 ms) |
| LOD | 0: 스트랜드, 3~5: 카드/보간, 6~7: 단순 메시 | LOD 0부터 카드 |
| 충돌 | `UGroomComponent` + 물리(강체) | 없음 |
| 바인딩 | `UGroomBindingAsset`(스켈레탈 메시 지정) | 스켈레탈 메시 부착(소켓) |
| 플랫폼 | PC·콘솔(플러그인 `HairStrands`) | 전 플랫폼 |
| 제작 | Groom 에디터/DCC 플러그인 | 일반 메시 파이프라인 |

실무 판단:

- **플레이어 캐릭터 1~2명**: Groom. LOD 0~2만 스트랜드, 3 이상 카드.
- **주요 NPC**: 카드 + 높은 텍스처 밀도(가닥 노멀/알파).
- **군중**: 카드 또는 헤어를 메시에 병합.
- Groom은 **바인딩이 스켈레탈 메시 기준**이므로, 의상 슬롯을 바꿔도 머리 메시가 바뀌지 않는 한 재바인딩은 필요 없다. 다만 체형 스케일을 크게 바꾸면 Groom이 따라 늘어나므로 스케일 변경 시 재바인딩 또는 스케일 보정이 필요하다.

```cpp
// 헤어는 ID만 데이터로 들고, 실제 교체는 구현체(서브클래스·BP)가 한다.
// Groom 모듈 의존성을 캐릭터 본체에서 떼어내는 것이 목적이다.
void AModularCharacter::SetHairStyle(FName StyleId)
{
    Customization.HairStyleId = StyleId;
    OnHairStyleChanged(StyleId);
}

// 구현체 쪽(HairStrands 모듈을 아는 서브클래스/BP)
//   GroomComponent->SetGroomAsset(NewGroom);       // 스타일 에셋
//   GroomComponent->SetBindingAsset(NewBinding);   // 메시 바인딩
//   UMaterialInstanceDynamic* HairMID = GroomComponent->CreateDynamicMaterialInstance(0);
//   HairMID->SetVectorParameterValue(TEXT("HairColor"), Customization.HairTint.Value);
```

### 4.6 데이터 구조·직렬화·복제

`FCharacterCustomizationData` 하나로 저장·복제·프리셋을 모두 처리한다. 필드를 세 종류로 나눈다.

| 종류 | 예 | 복제 | 저장 |
| --- | --- | --- | --- |
| 이산 ID | 슬롯별 `FPrimaryAssetId`, 헤어 스타일 ID | 필요 | 필요 |
| 연속 값 | 모프 가중치, 스케일, 색 | 필요(압축) | 필요 |
| 로컬 전용 | 로드된 메시 포인터, MID, 캐시 | 불필요 | 불필요 |

#### 네트워크 직렬화 압축

`NetSerialize`를 직접 구현하면 필드당 4바이트 float를 1바이트로 줄일 수 있다. 캐릭터 1명당 외형 데이터가 200바이트에서 40바이트로 줄면 20명 기준 3.2 KB가 절약되고, 이는 접속 시·리스폰 시 체감 차이로 나타난다.

| 필드 | 원본 | 직렬화 | 정밀도 |
| --- | --- | --- | --- |
| 모프 가중치 | float(4 B) | `uint8`(1 B) | 1/255 ≈ 0.4 % |
| 색(RGBA) | FLinearColor(16 B) | `uint8 × 4`(4 B) | 채널당 8비트 |
| 스케일(0.85~1.15) | float(4 B) | `uint8`(1 B) | 0.12 % |
| 슬롯 아이템 | `FPrimaryAssetId` | 타입 FName + 이름 FName | 그대로 |
| 슬롯 수 | — | `uint8`(1 B) | 최대 255 슬롯 |

```cpp
bool FCharacterCustomizationData::NetSerialize(FArchive& Ar, UPackageMap* Map, bool& bOutSuccess)
{
    uint8 SlotCount = static_cast<uint8>(FMath::Min(Slots.Num(), 255));
    Ar.SerializeBits(&SlotCount, 8);
    if (Ar.IsLoading()) { Slots.SetNum(SlotCount); }

    for (uint8 Index = 0; Index < SlotCount; ++Index)
    {
        FClothingSlotState& Slot = Slots[Index];
        if (Ar.IsLoading()) { Slot = FClothingSlotState(); }

        uint8 SlotId = static_cast<uint8>(Slot.Slot);
        Ar.SerializeBits(&SlotId, 8);
        if (Ar.IsLoading()) { Slot.Slot = static_cast<EClothingSlot>(SlotId); }

        // PrimaryAssetId는 FName 두 개로 나눠 보낸다(FName은 네트워크 아카이브에서 문자열로 직렬화).
        FName AssetType = Slot.ItemId.PrimaryAssetType.GetName();
        FName AssetName = Slot.ItemId.PrimaryAssetName;
        Ar << AssetType;
        Ar << AssetName;
        if (Ar.IsLoading())
        {
            Slot.ItemId = FPrimaryAssetId(FPrimaryAssetType(AssetType), AssetName);
        }

        uint8 ColorCount = static_cast<uint8>(FMath::Min(Slot.Colors.Num(), 8));
        Ar.SerializeBits(&ColorCount, 4);
        if (Ar.IsLoading()) { Slot.Colors.SetNum(ColorCount); }

        for (uint8 ColorIndex = 0; ColorIndex < ColorCount; ++ColorIndex)
        {
            FClothingColorParameter& Color = Slot.Colors[ColorIndex];
            Ar << Color.ParameterName;
            uint8 Channels[4] = { 0, 0, 0, 0 };
            if (Ar.IsSaving())
            {
                Channels[0] = static_cast<uint8>(FMath::Clamp(Color.Value.R * 255.f, 0.f, 255.f));
                Channels[1] = static_cast<uint8>(FMath::Clamp(Color.Value.G * 255.f, 0.f, 255.f));
                Channels[2] = static_cast<uint8>(FMath::Clamp(Color.Value.B * 255.f, 0.f, 255.f));
                Channels[3] = static_cast<uint8>(FMath::Clamp(Color.Value.A * 255.f, 0.f, 255.f));
            }
            Ar.SerializeBits(Channels, 8);
            Ar.SerializeBits(Channels + 1, 8);
            Ar.SerializeBits(Channels + 2, 8);
            Ar.SerializeBits(Channels + 3, 8);
            if (Ar.IsLoading())
            {
                Color.Value = FLinearColor(Channels[0] / 255.f, Channels[1] / 255.f,
                                           Channels[2] / 255.f, Channels[3] / 255.f);
            }
        }
    }

    bOutSuccess = true;
    return true;
}
```

#### 저장(SaveGame)

```cpp
UCLASS()
class MYGAME_API UCharacterSaveGame : public USaveGame
{
    GENERATED_BODY()

public:
    /** 구조 변경 시 올린다. 로드 시 마이그레이션이 필요하다. */
    UPROPERTY() int32 DataVersion = 1;

    UPROPERTY() FCharacterCustomizationData Customization;

    /** 프리셋(로드아웃) 목록. 이름 + 데이터. */
    UPROPERTY() TArray<FCharacterPreset> Presets;
};

void UMySaveSubsystem::SaveCharacter(const FCharacterCustomizationData& Data)
{
    UCharacterSaveGame* Save = Cast<UCharacterSaveGame>(
        UGameplayStatics::CreateSaveGameObject(UCharacterSaveGame::StaticClass()));
    if (!Save) { return; }

    Save->DataVersion = 1;
    Save->Customization = Data;
    UGameplayStatics::SaveGameToSlot(Save, TEXT("Character"), 0);
}
```

버전 관리 규칙: 필드를 추가할 때는 **기본값을 갖는 필드**로 추가하고 `DataVersion`을 올린다. 로드 시 버전이 낮으면 기본값으로 채운다. 인덱스 기반 배열(모프 30개를 순서대로 저장)은 절대 쓰지 않는다 — 순서가 바뀌면 얼굴이 뒤집힌다. 항상 **이름 키(`FName`) 기반**으로 저장한다.

#### 복제

```cpp
UPROPERTY(ReplicatedUsing = OnRep_Customization)
FCharacterCustomizationData Customization;

void AModularCharacter::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);

    // 소유자에게는 즉시, 다른 클라이언트에는 시뮬레이티드 프록시로 복제한다.
    DOREPLIFETIME(AModularCharacter, Customization);
}

void AModularCharacter::OnRep_Customization()
{
    ApplyCustomization(Customization);   // 메시·색·모프·마스크 일괄 적용
}
```

주의: `ApplyCustomization`은 **비동기 로드를 포함**하므로 `OnRep`에서 바로 모든 메시가 바뀌지 않는다. 1~3프레임 동안 기본 외형이 보인다면, 캐릭터 스폰 시 "외형 데이터가 도착할 때까지 메시를 숨기거나 단색 프록시를 보여주는" 처리가 필요하다.

### 4.7 커스터마이징 UI와 프리뷰

| 요소 | 구현 | 주의 |
| --- | --- | --- |
| 프리뷰 캐릭터 | 별도 레벨(또는 `SceneCapture2D` + 전용 조명) | 실제 라이팅과 다르면 인게임에서 다르게 보인다 |
| 회전 | 프리뷰 전용 카메라, 캐릭터 회전 | 액터 회전이 아니라 카메라 회전으로 |
| 조명 | 3점 조명 + 환경광, 실제 스카이와 유사하게 | 실내/실외 프리셋 2개 |
| 애니메이션 | Idle 1개 + 회전 | 매 프레임 재생, 표정은 선택 |
| 확대 | 얼굴 확대 시 모프·피부·헤어 LOD 0 강제 | `SetForcedLodModel(0)` |
| 검증 | "이 조합은 허용되지 않음" 규칙 | 서버에서도 검증(클라이언트 신뢰 금지) |

프리뷰가 인게임과 다르게 보이는 가장 흔한 원인은 **조명과 포스트프로세스**다. 프리뷰 전용 레벨에 인게임과 같은 `PostProcessVolume`·노출 설정을 복제하고, 가능하면 인게임 씬의 한 구석을 프리뷰로 쓰는 것이 정확하다.

### 4.8 커스터마이징 캐릭터의 비용 예산

| 비용 | PC(모듈러 + Groom + 클로스) | 측정 |
| --- | --- | --- |
| 스킨(6부위) | 0.4~0.8 ms | `stat gpu` |
| 애니메이션(1회 평가 + 팔로어 스킨) | 0.4~0.7 ms | `stat anim` |
| 클로스(망토 1) | 0.3~1.0 ms | `stat physics` |
| Groom(스트랜드 LOD0) | 0.5~1.5 ms | `stat gpu` |
| 드로우콜(6부위 + 장비) | 10~20 | `stat scenerendering` |
| 복제(외형 데이터) | 40~80 B/스폰 | `stat net` |

합계 2~4 ms는 60 fps 예산의 12~24 %다. **화면에 플레이어 1명 + NPC 10명**이 있다면 NPC는 이 예산을 쓸 수 없다. NPC는 모듈러 3부위 + 카드 헤어 + 클로스 없음으로 설계한다.

### 4.9 커스터마이징에서 자주 터지는 것

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 옷 색이 안 바뀐다 | MID를 만들었지만 컴포넌트에 설정하지 않음 / 파라미터 이름 오타 | `SetMaterial` 확인, 파라미터 이름을 상수로 관리 |
| 색을 바꾸면 다른 캐릭터도 바뀐다 | 원본 머티리얼 에셋을 수정 | 반드시 MID 사용 |
| 프리셋을 불러오면 얼굴이 뒤집힌다 | 인덱스 기반 저장 | `FName` 키 기반으로 |
| 멀티에서 옷이 다르게 보인다 | `ResolvedMesh`(로컬)만 복제, ID는 복제 안 함 | ID를 복제하고 각 클라이언트가 해석 |
| 모프가 절반만 적용된다 | 팔로어 커브 초기화, 또는 팔로어에 모프가 없음 | 3.2절 / 4.2절 |
| Groom이 몸을 뚫는다 | 바인딩이 오래된 메시 기준 | 재바인딩 또는 스케일 보정 |
| 장비 교체 시 0.5초 히치 | 동기 로드 | `RequestAsyncLoad` |
| 체형을 키웠는데 카메라가 발을 본다 | 캡슐·스프링암 미보정 | 4.3절 |
| 커스터마이징 후 그림자가 이상하다 | `bAffectDynamicIndirectLighting` / 거리 필드 미갱신 | 메시 교체 후 `MarkRenderStateDirty` |

---

## 5. 예제 코드와 검증

### 5.1 파일 구성

| 파일 | 내용 |
| --- | --- |
| [`examples/unreal_cpp_character/CharacterCustomizationTypes.h`](../examples/unreal_cpp_character/CharacterCustomizationTypes.h) | `EClothingSlot`, `UClothingItemDefinition`(에셋 매니저가 스캔하는 정의), `FClothingColorParameter`, `FCharacterMorphTarget`, `FClothingSlotState`, `FCharacterCustomizationData`. `NetSerialize`와 `TStructOpsTypeTraits`로 복제 지원 |
| [`examples/unreal_cpp_character/ModularCharacter.h`](../examples/unreal_cpp_character/ModularCharacter.h) | `AModularCharacter`: 부위별 `USkeletalMeshComponent`, 리더 포즈 초기화, 장착/해제, 모프, 색, 바디 마스크, 서버 RPC, 복제 델리게이트 |
| [`examples/unreal_cpp_character/ModularCharacter.cpp`](../examples/unreal_cpp_character/ModularCharacter.cpp) | 구현. 비동기 로드·경쟁 조건 검사·팔로어 모프 재적용·MID 캐시·복제 |
| [`tests/test_cpp_examples.py`](../tests/test_cpp_examples.py) | C++ 예제의 구조 검증(헤더/구현 정합, 매크로 짝, NetSerialize 대칭, 복제 프로퍼티 대응) |

### 5.2 프로젝트에 넣는 방법

```
MyGame/
├── Source/MyGame/
│   ├── MyGame.Build.cs
│   └── Character/
│       ├── CharacterCustomizationTypes.h
│       ├── ModularCharacter.h
│       └── ModularCharacter.cpp
```

1. 세 파일을 `Source/MyGame/Character/`에 복사한다.
2. `MYGAME_API` 매크로를 프로젝트 모듈 이름에 맞춘다.
3. `Build.cs`에 필요한 모듈을 추가한다. 예제는 엔진 기본 모듈만 쓴다(`Core`, `CoreUObject`, `Engine`).
4. `AModularCharacter`를 상속한 블루프린트를 만들고, `Mesh`(리더)에 몸 메시를 지정한다.
5. 각 부위 컴포넌트는 C++에서 생성되므로 블루프린트에서 메시만 할당하면 된다.

주의: `.generated.h`를 포함하는 헤더는 **UHT 빌드**가 필요하므로, 이 저장소의 Python 테스트는 컴파일 대신 **구조·정합성**을 검증한다(헤더 선언 ↔ 구현 정의, 매크로 짝, 직렬화 대칭, 복제 프로퍼티 대응).

### 5.3 검증 실행

```bash
python -m unittest tests.test_cpp_examples -v
```

검사 항목:

| 검사 | 의미 |
| --- | --- |
| 파일 존재·인코딩 | UTF-8, `#pragma once`, `CoreMinimal.h` 포함, `.generated.h` 마지막 포함 |
| 괄호 균형 | 문자열·주석 제거 후 `{}`, `()`, `[]` 균형 |
| 매크로 짝 | `UCLASS`/`USTRUCT`/`UENUM`/`UINTERFACE` 다음에 선언이 오는가 |
| 선언 ↔ 정의 | 헤더에서 선언한 멤버 함수가 `.cpp`에 `클래스명::함수명`으로 정의됐는가 |
| 프로퍼티 형식 | `UPROPERTY` 뒤 선언이 `;`로 끝나는가 |
| 직렬화 대칭 | `NetSerialize`에 저장/로드 경로가 모두 있는가, `bOutSuccess` 설정 |
| 복제 대응 | `ReplicatedUsing` 프로퍼티마다 `OnRep_` 함수가 선언·정의됐는가 |
| 복제 등록 | `GetLifetimeReplicatedProps`에 `DOREPLIFETIME`이 있는가 |
| 리더 포즈 | `SetLeaderPoseComponent` 사용, 팔로어 틱 설정이 명시됐는가 |
| 열거형 | `uint8` 기반, `Count`가 마지막인가 |

이 테스트는 컴파일을 대체하지 않는다. 목적은 **리팩터링 중 깨지기 쉬운 정합성**(선언만 하고 구현을 잊은 함수, `OnRep` 누락, `NetSerialize`의 한쪽 경로 누락)을 CI에서 잡는 것이다.

---

## 6. 체크리스트와 참고 자료

### 6.1 캐릭터 시스템 착수 체크리스트

**설계**

- [ ] `ABaseCharacter`에 들어갈 공통 컴포넌트를 확정했는가
- [ ] PC/NPC의 이동·회전 설정 차이를 표로 문서화했는가
- [ ] 입력 컨텍스트(걷기/차량/UI/컷신) 목록과 전환 지점을 정했는가
- [ ] NPC 판단을 BT로 할지 StateTree로 할지 정했는가(상태 5개 기준)
- [ ] 캐릭터 예산표(삼각형·본·머티리얼·모프·클로스)를 채웠는가

**모듈러 의상**

- [ ] 슬롯 목록과 슬롯별 예산을 정했는가
- [ ] 모든 슬롯 메시가 같은 스켈레톤·같은 LOD 수를 쓰는가
- [ ] 리더 포즈 팔로어의 틱 설정(애니메이션/클로스)을 슬롯별로 정했는가
- [ ] 모프를 애님 커브로 돌릴지, 팔로어에 직접 적용할지 정했는가
- [ ] 장비 교체 경로에 비동기 로드와 경쟁 조건 검사가 있는가
- [ ] 클리핑 방어 4단계 중 어디까지 적용했는가

**외모 커스터마이징**

- [ ] 파라미터를 "연속(모프/스케일) / 이산(ID)"으로 분류했는가
- [ ] 저장 형식이 이름 키 기반인가(인덱스 금지)
- [ ] `NetSerialize` 압축으로 캐릭터당 바이트 예산을 맞췄는가
- [ ] 서버가 외형 데이터를 검증하는가(허용되지 않은 조합 차단)
- [ ] 프리뷰 조명·노출이 인게임과 같은가
- [ ] MID 수를 캐릭터당 예산(6~10) 안으로 관리하는가

**성능**

- [ ] Significance Manager 또는 Budget Allocator를 적용했는가
- [ ] NPC 복제 빈도(`NetUpdateFrequency`)를 거리·중요도별로 낮췄는가
- [ ] LOD별 클로스·모프·얼굴 비용을 끄는 규칙이 있는가
- [ ] 20명 동시 등장 시 `stat anim` / `stat gpu` 수치를 기록했는가

### 6.2 참고 자료

**엔진 공식**

- Modular Characters in Unreal Engine — 리더 포즈(Leader Pose) 기반 모듈러 캐릭터 구성.
- Skeletal Mesh Animation System / Animation Budget Allocator — 예산 기반 애니메이션 감축.
- Significance Manager — 거리·중요도 기반 틱·애니메이션 관리.
- Chaos Cloth — 의상 시뮬레이션 설정과 성능.
- Hair Strands(Groom) — 스트랜드 헤어 파이프라인과 LOD.
- Gameplay Ability System — 아이템·능력 연계.
- StateTree — 5.4 이후 권장 NPC 상태 관리.
- MassEntity / MassCrowd / CitySample — 대규모 NPC.

**서적**

- Jason Gregory, *Game Engine Architecture* — 캐릭터 애니메이션·스키닝 파이프라인의 이론.
- Ian Millington, *AI for Games* — NPC 판단·경로·군중의 알고리즘.
- Simon Alexanderson 외, *Modular Character Rigging* 관련 GDC 자료 — 모듈러 의상의 실무 사례(업계 강연 자료 일반).

**함께 보는 저장소 문서**

- [open_world_content_and_architecture_guide.md](open_world_content_and_architecture_guide.md) — 탈것·아이템·건물·배치와 건축 스케일.
- [open_world_creation_pipeline.md](open_world_creation_pipeline.md) — 월드 스트리밍·HLOD·라이팅.
- [blender_pipeline.md](blender_pipeline.md) — 캐릭터 리토폴로지·베이킹(경로 B).
