// Copyright (c) 2026. Example code for the Unreal character customization guide.
//
// ModularCharacter.cpp

#include "ModularCharacter.h"

#include "CharacterCustomizationTypes.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StreamableManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Net/UnrealNetwork.h"

namespace
{
    /** 팔로어 틱 포즈가 필요한 슬롯(클로스 시뮬레이션이 컴포넌트 틱을 요구한다). */
    bool SlotNeedsTickPose(EClothingSlot Slot)
    {
        return Slot == EClothingSlot::Back;
    }

    /** 슬롯별 가림 마스크 파라미터 이름. 예: "Coverage_Torso" */
    FName MakeCoverageParameterName(EClothingSlot Slot)
    {
        const UEnum* SlotEnum = StaticEnum<EClothingSlot>();
        const FString SlotName = SlotEnum
            ? SlotEnum->GetNameStringByValue(static_cast<int64>(Slot))
            : TEXT("Unknown");

        return FName(*FString::Printf(TEXT("Coverage_%s"), *SlotName));
    }
}

AModularCharacter::AModularCharacter(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    // 의상 컴포넌트는 몸(Mesh)에 부착한다. 본 트랜스폼은 리더 포즈로 공유한다.
    HeadMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("HeadMesh"));
    TorsoMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("TorsoMesh"));
    LegsMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("LegsMesh"));
    HandsMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("HandsMesh"));
    FeetMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("FeetMesh"));
    BackMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("BackMesh"));

    TArray<USkeletalMeshComponent*> SlotComponents = {
        HeadMesh, TorsoMesh, LegsMesh, HandsMesh, FeetMesh, BackMesh
    };

    for (USkeletalMeshComponent* SlotComponent : SlotComponents)
    {
        if (!SlotComponent)
        {
            continue;
        }

        SlotComponent->SetupAttachment(GetMesh());
        SlotComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        SlotComponent->SetGenerateOverlapEvents(false);
        SlotComponent->SetCanEverAffectNavigation(false);
        SlotComponent->bCastHiddenShadow = false;
        SlotComponent->bCastDynamicShadow = true;
        SlotComponent->SetIsReplicated(false);
        SlotComponent->SetVisibility(false);
    }
}

// ---------------------------------------------------------------------------
// 생명주기
// ---------------------------------------------------------------------------

void AModularCharacter::BeginPlay()
{
    Super::BeginPlay();

    InitializeLeaderPose();

    // SetMorphTarget은 액터 생성 중(생성자/OnConstruction)에 안전하지 않으므로 여기서 적용한다.
    ApplyCustomization(Customization);
}

void AModularCharacter::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

    if (!bRefreshFollowerMorphs || Customization.MorphTargets.Num() == 0 || FollowerMeshes.Num() == 0)
    {
        return;
    }

    MorphRefreshAccumulator += DeltaSeconds;
    if (FollowerMorphRefreshInterval <= 0.f || MorphRefreshAccumulator >= FollowerMorphRefreshInterval)
    {
        MorphRefreshAccumulator = 0.f;
        RefreshFollowerMorphs();
    }
}

void AModularCharacter::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);

    // 외형은 모든 클라이언트가 알아야 한다(다른 사람이 내 캐릭터를 본다).
    DOREPLIFETIME(AModularCharacter, Customization);
}

void AModularCharacter::OnRep_Customization()
{
    // 복제된 데이터는 메시 포인터가 비어 있으므로 ItemId로 해석해 다시 적용한다.
    ApplyCustomization(Customization);
}

// ---------------------------------------------------------------------------
// 리더 포즈
// ---------------------------------------------------------------------------

void AModularCharacter::InitializeLeaderPose()
{
    FollowerMeshes.Reset();

    for (int32 SlotIndex = 0; SlotIndex < static_cast<int32>(EClothingSlot::Count); ++SlotIndex)
    {
        USkeletalMeshComponent* Follower = GetMeshForSlot(static_cast<EClothingSlot>(SlotIndex));
        if (!Follower || Follower == GetMesh())
        {
            continue;
        }

        // bInFollowerShouldTickPose=false → 팔로어는 애니메이션 그래프를 평가하지 않는다.
        // 클로스가 있는 슬롯만 컴포넌트 틱이 필요하므로 true로 둔다.
        const bool bShouldTickPose = SlotNeedsTickPose(static_cast<EClothingSlot>(SlotIndex));
        Follower->SetLeaderPoseComponent(GetMesh(), /*bForceUpdate*/ true, bShouldTickPose);

        UpdateFollowerSettings(Follower);
        FollowerMeshes.Add(Follower);
    }
}

void AModularCharacter::UpdateFollowerSettings(USkeletalMeshComponent* Follower) const
{
    if (!Follower)
    {
        return;
    }

    // LOD를 리더와 동기화한다(따로 놀면 원거리에서 옷만 고밀도로 남는다).
    Follower->bSyncAttachParentLOD = true;

    // 팔로어 바운즈는 실제 옷보다 작다. 리더 바운즈를 써야 화면 가장자리에서 먼저 컬되지 않는다.
    Follower->bUseAttachParentBound = true;

    // 팔로어는 자체 애니메이션·물리를 갖지 않는다.
    Follower->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::OnlyTickPoseWhenRendered;
    Follower->bEnableUpdateRateOptimizations = true;
    Follower->SetSimulatePhysics(false);
    Follower->SetAllBodiesBelowSimulatePhysics(NAME_None, false, /*bIncludeSelf*/ true);
    Follower->ClothBlendWeight = 1.f;
}

// ---------------------------------------------------------------------------
// 조회
// ---------------------------------------------------------------------------

USkeletalMeshComponent* AModularCharacter::GetMeshForSlot(EClothingSlot Slot) const
{
    switch (Slot)
    {
    case EClothingSlot::Head:   return HeadMesh;
    case EClothingSlot::Torso:  return TorsoMesh;
    case EClothingSlot::Legs:   return LegsMesh;
    case EClothingSlot::Hands:  return HandsMesh;
    case EClothingSlot::Feet:   return FeetMesh;
    case EClothingSlot::Back:   return BackMesh;
    default:                    return nullptr;
    }
}

// ---------------------------------------------------------------------------
// 적용
// ---------------------------------------------------------------------------

void AModularCharacter::ApplyCustomization(const FCharacterCustomizationData& NewData)
{
    Customization = NewData;

    // 1) 상태에 없는 슬롯은 비운다(이전 외형의 잔여 메시 제거).
    for (int32 SlotIndex = 0; SlotIndex < static_cast<int32>(EClothingSlot::Count); ++SlotIndex)
    {
        const EClothingSlot Slot = static_cast<EClothingSlot>(SlotIndex);
        if (!Customization.FindSlot(Slot))
        {
            ApplySlotMesh(Slot, nullptr);
        }
    }

    // 2) 장착 슬롯을 적용한다. 이미 로드된 메시는 즉시, 아니면 비동기 로드 후 적용.
    for (FClothingSlotState& State : Customization.Slots)
    {
        if (State.Slot >= EClothingSlot::Count)
        {
            continue;
        }

        if (USkeletalMesh* Resolved = ResolveSlotMesh(State))
        {
            ApplySlotMesh(State.Slot, Resolved);
        }
        else if (!State.ResolvedMesh.IsNull())
        {
            RequestSlotLoad(State.Slot, State.ResolvedMesh.ToSoftObjectPath());
        }
    }

    // 3) 색·모프·마스킹.
    UpdateBodyMask();
    ApplySkinParameters(Customization);
    ApplyMorphTargets();

    OnCustomizationApplied();
}

void AModularCharacter::EquipMesh(EClothingSlot Slot, TSoftObjectPtr<USkeletalMesh> Mesh, bool bHideBodyUnderneath)
{
    if (!CanModifyCustomization() || Slot >= EClothingSlot::Count)
    {
        return;
    }

    if (Mesh.IsNull())
    {
        ClearSlot(Slot);
        return;
    }

    FClothingSlotState& State = GetOrAddSlotState(Slot);
    State.Slot = Slot;
    State.ResolvedMesh = Mesh;
    State.bHideBodyUnderneath = bHideBodyUnderneath;

    if (USkeletalMesh* Loaded = Mesh.Get())
    {
        ApplySlotMesh(Slot, Loaded);          // 대부분의 경우 이미 로드되어 있다.
        UpdateBodyMask();
        ApplyMorphTargets();
    }
    else
    {
        RequestSlotLoad(Slot, Mesh.ToSoftObjectPath());
    }

    // 서버가 아니면 판정을 요청한다(서버가 다르게 판정하면 OnRep이 되돌린다).
    if (!HasAuthority())
    {
        ServerSetCustomization(Customization);
    }
}

void AModularCharacter::ClearSlot(EClothingSlot Slot)
{
    if (!CanModifyCustomization() || Slot >= EClothingSlot::Count)
    {
        return;
    }

    if (FClothingSlotState* State = Customization.FindSlotMutable(Slot))
    {
        State->ItemId = FPrimaryAssetId();
        State->ResolvedMesh.Reset();
        State->Colors.Reset();
    }

    PendingLoads.Remove(Slot);
    ApplySlotMesh(Slot, nullptr);
    UpdateBodyMask();

    if (!HasAuthority())
    {
        ServerSetCustomization(Customization);
    }
}

void AModularCharacter::ApplySlotMesh(EClothingSlot Slot, USkeletalMesh* Mesh)
{
    USkeletalMeshComponent* Comp = GetMeshForSlot(Slot);
    if (!Comp)
    {
        return;
    }

    if (!Mesh)
    {
        Comp->SetSkeletalMesh(nullptr);
        Comp->SetVisibility(false);
        return;
    }

    if (Comp->GetSkeletalMeshAsset() == Mesh)
    {
        Comp->SetVisibility(true);
        return;
    }

    Comp->SetSkeletalMesh(Mesh);
    Comp->SetLeaderPoseComponent(GetMesh(), /*bForceUpdate*/ true, SlotNeedsTickPose(Slot));
    UpdateFollowerSettings(Comp);
    Comp->SetVisibility(true);

    // 머티리얼이 새로 만들어졌으므로 색 파라미터를 다시 적용한다.
    if (const FClothingSlotState* State = Customization.FindSlot(Slot))
    {
        for (const FClothingColorParameter& Color : State->Colors)
        {
            for (int32 MaterialIndex = 0; MaterialIndex < Comp->GetNumMaterials(); ++MaterialIndex)
            {
                if (UMaterialInstanceDynamic* MID = GetOrCreateSlotMID(Comp, MaterialIndex))
                {
                    MID->SetVectorParameterValue(Color.ParameterName, Color.Value);
                }
            }
        }
    }
}

void AModularCharacter::RequestSlotLoad(EClothingSlot Slot, const FSoftObjectPath& Path)
{
    if (!Path.IsValid())
    {
        return;
    }

    // 슬롯별 마지막 요청을 기록해 두고, 늦게 도착한 콜백은 폐기한다(경쟁 조건 방지).
    PendingLoads.Add(Slot, Path);

    const FStreamableDelegate Delegate = FStreamableDelegate::CreateUObject(
        this, &AModularCharacter::OnSlotMeshLoaded, Slot, Path);

    UAssetManager::GetStreamableManager().RequestAsyncLoad(Path, Delegate);
}

void AModularCharacter::OnSlotMeshLoaded(EClothingSlot Slot, FSoftObjectPath Path)
{
    const FSoftObjectPath* Pending = PendingLoads.Find(Slot);
    if (!Pending || *Pending != Path)
    {
        return;   // 그 사이 다른 메시로 바뀌었다.
    }

    PendingLoads.Remove(Slot);

    USkeletalMesh* Loaded = Cast<USkeletalMesh>(Path.ResolveObject());
    if (!Loaded)
    {
        UE_LOG(LogTemp, Warning, TEXT("모듈러 캐릭터: %s 슬롯 메시 로드 실패 (%s)"), *UEnum::GetValueAsString(Slot), *Path.ToString());
        return;
    }

    FClothingSlotState& State = GetOrAddSlotState(Slot);
    State.ResolvedMesh = Loaded;
    ApplySlotMesh(Slot, Loaded);
    UpdateBodyMask();
}

USkeletalMesh* AModularCharacter::ResolveSlotMesh(FClothingSlotState& State)
{
    if (!State.ResolvedMesh.IsNull())
    {
        return State.ResolvedMesh.Get();
    }

    if (!State.ItemId.IsValid())
    {
        return nullptr;
    }

    // 아이템 정의(데이터 에셋)에서 메시를 해석한다. 정의는 작은 데이터라 동기 로드가 허용된다.
    const FSoftObjectPath DefinitionPath = UAssetManager::Get().GetPrimaryAssetPath(State.ItemId);
    if (!DefinitionPath.IsValid())
    {
        return nullptr;
    }

    const UClothingItemDefinition* Definition = Cast<UClothingItemDefinition>(DefinitionPath.TryLoad());
    if (!Definition)
    {
        return nullptr;
    }

    State.ResolvedMesh = Definition->Mesh;
    return State.ResolvedMesh.Get();
}

FClothingSlotState& AModularCharacter::GetOrAddSlotState(EClothingSlot Slot)
{
    if (FClothingSlotState* Existing = Customization.FindSlotMutable(Slot))
    {
        return *Existing;
    }

    FClothingSlotState NewState;
    NewState.Slot = Slot;
    const int32 NewIndex = Customization.Slots.Add(NewState);
    return Customization.Slots[NewIndex];
}

UMaterialInstanceDynamic* AModularCharacter::GetOrCreateSlotMID(USkeletalMeshComponent* TargetComp, int32 MaterialIndex)
{
    if (!TargetComp || MaterialIndex < 0 || MaterialIndex >= TargetComp->GetNumMaterials())
    {
        return nullptr;
    }

    // 이미 MID면 그대로 쓴다(컴포넌트가 소유하므로 별도 캐시가 필요 없다).
    if (UMaterialInstanceDynamic* Existing = Cast<UMaterialInstanceDynamic>(TargetComp->GetMaterial(MaterialIndex)))
    {
        return Existing;
    }

    UMaterialInterface* Source = TargetComp->GetMaterial(MaterialIndex);
    if (!Source)
    {
        return nullptr;
    }

    return TargetComp->CreateDynamicMaterialInstance(MaterialIndex, Source);
}

// ---------------------------------------------------------------------------
// 모프 타깃
// ---------------------------------------------------------------------------

bool AModularCharacter::SetMorphTargetWeight(FName MorphName, float Weight)
{
    if (!CanModifyCustomization() || MorphName.IsNone())
    {
        return false;
    }

    const float ClampedWeight = FMath::Clamp(Weight, 0.f, 1.f);

    FCharacterMorphTarget* Existing = Customization.MorphTargets.FindByPredicate(
        [MorphName](const FCharacterMorphTarget& Entry) { return Entry.Name == MorphName; });

    if (Existing)
    {
        Existing->Weight = ClampedWeight;
    }
    else
    {
        FCharacterMorphTarget NewMorph;
        NewMorph.Name = MorphName;
        NewMorph.Weight = ClampedWeight;
        Customization.MorphTargets.Add(NewMorph);
    }

    ApplyMorphTargets();

    if (!HasAuthority())
    {
        ServerSetCustomization(Customization);
    }

    return true;
}

void AModularCharacter::ApplyMorphTargets()
{
    USkeletalMeshComponent* Body = GetMesh();
    if (!Body)
    {
        return;
    }

    for (const FCharacterMorphTarget& Morph : Customization.MorphTargets)
    {
        if (Morph.Name.IsNone())
        {
            continue;
        }

        Body->SetMorphTarget(Morph.Name, FMath::Clamp(Morph.Weight, 0.f, 1.f));
    }

    // 리더의 morph 커브만 팔로어로 복사되므로, 직접 설정한 값은 팔로어에 매 주기 다시 넣는다.
    if (bRefreshFollowerMorphs)
    {
        RefreshFollowerMorphs();
    }
}

void AModularCharacter::RefreshFollowerMorphs()
{
    if (Customization.MorphTargets.Num() == 0)
    {
        return;
    }

    for (USkeletalMeshComponent* Follower : FollowerMeshes)
    {
        if (!Follower || !Follower->GetSkeletalMeshAsset())
        {
            continue;
        }

        for (const FCharacterMorphTarget& Morph : Customization.MorphTargets)
        {
            if (Morph.Name.IsNone())
            {
                continue;
            }

            // bRemoveZeroWeight=false: 0 가중치 엔트리를 매 프레임 지웠다 넣는 낭비를 막는다.
            Follower->SetMorphTarget(Morph.Name, FMath::Clamp(Morph.Weight, 0.f, 1.f), /*bRemoveZeroWeight*/ false);
        }
    }
}

// ---------------------------------------------------------------------------
// 색·스킨·마스킹
// ---------------------------------------------------------------------------

bool AModularCharacter::SetColorParameter(EClothingSlot Slot, FName ParameterName, FLinearColor Value)
{
    if (!CanModifyCustomization() || ParameterName.IsNone())
    {
        return false;
    }

    FClothingSlotState& State = GetOrAddSlotState(Slot);

    FClothingColorParameter* Existing = State.Colors.FindByPredicate(
        [ParameterName](const FClothingColorParameter& Entry) { return Entry.ParameterName == ParameterName; });

    if (Existing)
    {
        Existing->Value = Value;
    }
    else
    {
        State.Colors.Add(FClothingColorParameter(ParameterName, Value));
    }

    USkeletalMeshComponent* Comp = GetMeshForSlot(Slot);
    if (!Comp)
    {
        return false;
    }

    for (int32 MaterialIndex = 0; MaterialIndex < Comp->GetNumMaterials(); ++MaterialIndex)
    {
        if (UMaterialInstanceDynamic* MID = GetOrCreateSlotMID(Comp, MaterialIndex))
        {
            MID->SetVectorParameterValue(ParameterName, Value);
        }
    }

    if (!HasAuthority())
    {
        ServerSetCustomization(Customization);
    }

    return true;
}

void AModularCharacter::ApplySkinParameters(const FCharacterCustomizationData& Data)
{
    USkeletalMeshComponent* Body = GetMesh();
    if (!Body)
    {
        return;
    }

    for (int32 MaterialIndex = 0; MaterialIndex < Body->GetNumMaterials(); ++MaterialIndex)
    {
        UMaterialInstanceDynamic* MID = GetOrCreateSlotMID(Body, MaterialIndex);
        if (!MID)
        {
            continue;
        }

        MID->SetVectorParameterValue(Data.SkinTint.ParameterName, Data.SkinTint.Value);
        MID->SetScalarParameterValue(TEXT("FreckleAmount"), Data.FreckleAmount);
        MID->SetScalarParameterValue(TEXT("ScarAmount"), Data.ScarAmount);
    }
}

void AModularCharacter::SetHairStyle(FName StyleId)
{
    if (!CanModifyCustomization())
    {
        return;
    }

    Customization.HairStyleId = StyleId;

    // 실제 Groom/메시 교체는 구현체가 한다(플러그인 의존을 예제에서 분리).
    OnHairStyleChanged(StyleId);

    if (!HasAuthority())
    {
        ServerSetCustomization(Customization);
    }
}

void AModularCharacter::UpdateBodyMask()
{
    USkeletalMeshComponent* Body = GetMesh();
    if (!Body || !Body->GetSkeletalMeshAsset())
    {
        return;
    }

    for (int32 SlotIndex = 0; SlotIndex < static_cast<int32>(EClothingSlot::Count); ++SlotIndex)
    {
        const EClothingSlot Slot = static_cast<EClothingSlot>(SlotIndex);
        const FClothingSlotState* State = Customization.FindSlot(Slot);

        const bool bCovered = State && State->bHideBodyUnderneath && !State->ResolvedMesh.IsNull();
        const FName ParameterName = MakeCoverageParameterName(Slot);
        const float CoverageValue = bCovered ? 1.f : 0.f;

        for (int32 MaterialIndex = 0; MaterialIndex < Body->GetNumMaterials(); ++MaterialIndex)
        {
            if (UMaterialInstanceDynamic* MID = GetOrCreateSlotMID(Body, MaterialIndex))
            {
                MID->SetScalarParameterValue(ParameterName, CoverageValue);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// 서버 권위
// ---------------------------------------------------------------------------

bool AModularCharacter::CanModifyCustomization() const
{
    return HasAuthority() || IsLocallyControlled();
}

void AModularCharacter::ServerSetCustomization_Implementation(const FCharacterCustomizationData& NewData)
{
    if (!HasAuthority())
    {
        return;
    }

    // 서버 검증: 잘못된 슬롯·중복 슬롯을 제거한다. 아이템 소유 여부 등은 인벤토리에서 별도 검증한다.
    FCharacterCustomizationData Sanitized = NewData;
    Sanitized.Slots.RemoveAll([](const FClothingSlotState& Entry)
    {
        return Entry.Slot >= EClothingSlot::Count;
    });

    for (int32 Index = Sanitized.Slots.Num() - 1; Index >= 0; --Index)
    {
        const EClothingSlot Slot = Sanitized.Slots[Index].Slot;
        const bool bDuplicate = Sanitized.Slots.ContainsByPredicate(
            [Slot, Index, &Sanitized](const FClothingSlotState& Entry)
            {
                return Entry.Slot == Slot && (&Entry != &Sanitized.Slots[Index]);
            });

        if (bDuplicate)
        {
            Sanitized.Slots.RemoveAt(Index);
        }
    }

    // 서버에서는 OnRep이 호출되지 않으므로 직접 적용한다.
    ApplyCustomization(Sanitized);
}
