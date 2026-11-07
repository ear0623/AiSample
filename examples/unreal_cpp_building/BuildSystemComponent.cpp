// Copyright (c) 2026. Example code for the open world architecture guide (in-game building).
//
// BuildSystemComponent.cpp

#include "BuildSystemComponent.h"

#include "BuildManager.h"
#include "BuildingTypes.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Materials/MaterialInstanceDynamic.h"

namespace
{
    /** 반대편 소켓 이름을 만든다. Snap_Top ↔ Snap_Bottom, Snap_Left ↔ Snap_Right */
    FName MakeOppositeSocketName(FName InSocketName)
    {
        FString Name = InSocketName.ToString();

        if (Name.Contains(TEXT("_Bottom")))
        {
            return FName(*Name.Replace(TEXT("_Bottom"), TEXT("_Top")));
        }
        if (Name.Contains(TEXT("_Top")))
        {
            return FName(*Name.Replace(TEXT("_Top"), TEXT("_Bottom")));
        }
        if (Name.Contains(TEXT("_Left")))
        {
            return FName(*Name.Replace(TEXT("_Left"), TEXT("_Right")));
        }
        if (Name.Contains(TEXT("_Right")))
        {
            return FName(*Name.Replace(TEXT("_Right"), TEXT("_Left")));
        }

        return InSocketName;
    }
}

UBuildSystemComponent::UBuildSystemComponent(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = false;
}

void UBuildSystemComponent::BeginPlay()
{
    Super::BeginPlay();

    APawn* Pawn = GetOwningPawn();
    if (!Pawn || !Pawn->IsLocallyControlled())
    {
        return;   // 프리뷰는 로컬 플레이어에게만 필요하다.
    }

    PreviewMesh = NewObject<UStaticMeshComponent>(this, TEXT("BuildPreviewMesh"));
    if (PreviewMesh)
    {
        PreviewMesh->SetupAttachment(Pawn->GetRootComponent());
        PreviewMesh->RegisterComponent();
        PreviewMesh->SetMobility(EComponentMobility::Movable);
        PreviewMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        PreviewMesh->SetGenerateOverlapEvents(false);
        PreviewMesh->SetCastShadow(false);
        PreviewMesh->bReceivesDecals = false;
        PreviewMesh->SetVisibility(false);
    }
}

void UBuildSystemComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (PreviewMesh)
    {
        PreviewMesh->DestroyComponent();
        PreviewMesh = nullptr;
    }

    PreviewMID = nullptr;
    CachedManager = nullptr;

    Super::EndPlay(EndPlayReason);
}

APawn* UBuildSystemComponent::GetOwningPawn() const
{
    return Cast<APawn>(GetOwner());
}

ABuildManager* UBuildSystemComponent::GetBuildManager() const
{
    if (CachedManager)
    {
        return CachedManager;
    }

    if (UWorld* World = GetWorld())
    {
        CachedManager = Cast<ABuildManager>(UGameplayStatics::GetActorOfClass(World, ABuildManager::StaticClass()));
    }

    return CachedManager;
}

void UBuildSystemComponent::StartPreview(UBuildPieceDefinition* Definition)
{
    if (!Definition || !PreviewMesh)
    {
        return;
    }

    SelectedDefinition = Definition;
    bHasCachedTarget = false;
    LastResult = EPlacementResult::NoHit;

    if (UStaticMesh* Mesh = Definition->Mesh.LoadSynchronous())
    {
        PreviewMesh->SetStaticMesh(Mesh);

        if (PreviewMaterialBase)
        {
            PreviewMID = PreviewMesh->CreateDynamicMaterialInstance(0, PreviewMaterialBase);
        }
    }

    PreviewMesh->SetVisibility(false);
    SetComponentTickEnabled(true);
}

void UBuildSystemComponent::CancelPreview()
{
    SelectedDefinition = nullptr;
    bHasCachedTarget = false;
    LastResult = EPlacementResult::NoHit;
    SetPreviewVisible(false);
    SetComponentTickEnabled(false);
}

void UBuildSystemComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    if (SelectedDefinition)
    {
        UpdatePreview();
    }
}

void UBuildSystemComponent::SetPreviewVisible(bool bVisible)
{
    if (PreviewMesh)
    {
        PreviewMesh->SetVisibility(bVisible);
    }
}

bool UBuildSystemComponent::ComputeSnapTransform(const FHitResult& Hit, FVector& OutLocation, FQuat& OutRotation,
                                                FGuid& OutSupportPieceId) const
{
    if (!SelectedDefinition)
    {
        return false;
    }

    const APawn* Pawn = GetOwningPawn();
    if (!Pawn)
    {
        return false;
    }

    // ① 소켓 스냅: 기존 조각의 소켓과 내 조각의 반대편 소켓을 맞춘다.
    ABuildPieceActor* HitPiece = Cast<ABuildPieceActor>(Hit.GetActor());
    if (HitPiece && HitPiece->GetMeshComponent() && PreviewMesh && PreviewMesh->GetStaticMesh())
    {
        bool bFoundSocketSnap = false;
        float BestDistance = TNumericLimits<float>::Max();

        for (const FName OwnSocketName : SelectedDefinition->SnapSockets)
        {
            if (!PreviewMesh->DoesSocketExist(OwnSocketName))
            {
                continue;
            }

            const FName OtherSocketName = MakeOppositeSocketName(OwnSocketName);
            if (!HitPiece->GetMeshComponent()->DoesSocketExist(OtherSocketName))
            {
                continue;
            }

            // 다른 조각의 소켓(월드)과 내 조각의 소켓(로컬)을 일치시키는 트랜스폼.
            const FTransform OtherSocketWorld =
                HitPiece->GetMeshComponent()->GetSocketTransform(OtherSocketName, RTS_World);
            const FTransform OwnSocketLocal =
                PreviewMesh->GetSocketTransform(OwnSocketName, RTS_Component);

            const FTransform Candidate = OtherSocketWorld * OwnSocketLocal.Inverse();

            // 가장 "커서에 가까운" 소켓 쌍을 고른다.
            const float Distance = FVector::Dist(Candidate.GetLocation(), Hit.ImpactPoint);
            if (Distance < BestDistance)
            {
                BestDistance = Distance;
                OutLocation = Candidate.GetLocation();
                OutRotation = Candidate.GetRotation();
                OutSupportPieceId = HitPiece->PieceId;
                bFoundSocketSnap = true;
            }
        }

        if (bFoundSocketSnap)
        {
            return true;
        }
    }

    // ② 그리드 스냅: 표면 히트 지점을 그리드로 내리고, 요를 90도 단위로 맞춘다.
    OutLocation = BuildSnap::SnapToGrid(Hit.ImpactPoint, GridCm);

    const FRotator PawnYaw(0.f, Pawn->GetControlRotation().Yaw, 0.f);
    OutRotation = BuildSnap::SnapYawToQuarterTurns(PawnYaw.Quaternion());
    OutSupportPieceId = HitPiece ? HitPiece->PieceId : FGuid();

    return true;
}

void UBuildSystemComponent::UpdatePreview()
{
    UWorld* World = GetWorld();
    APawn* Pawn = GetOwningPawn();
    if (!World || !Pawn || !SelectedDefinition || !PreviewMesh)
    {
        return;
    }

    const APlayerController* PlayerController = Cast<APlayerController>(Pawn->GetController());
    if (!PlayerController)
    {
        return;
    }

    FVector ViewLocation;
    FRotator ViewRotation;
    PlayerController->GetPlayerViewPoint(ViewLocation, ViewRotation);

    const FVector TraceStart = ViewLocation;
    const FVector TraceEnd = ViewLocation + ViewRotation.Vector() * BuildRangeCm;

    FCollisionQueryParams QueryParams(SCENE_QUERY_STAT(BuildPreviewTrace), false, Pawn);
    QueryParams.AddIgnoredComponent(PreviewMesh);

    FHitResult Hit;
    if (!World->LineTraceSingleByChannel(Hit, TraceStart, TraceEnd, ECC_Visibility, QueryParams))
    {
        bHasCachedTarget = false;
        LastResult = EPlacementResult::NoHit;
        SetPreviewVisible(false);
        return;
    }

    FVector SnapLocation;
    FQuat SnapRotation;
    FGuid SupportPieceId;

    if (!ComputeSnapTransform(Hit, SnapLocation, SnapRotation, SupportPieceId))
    {
        bHasCachedTarget = false;
        LastResult = EPlacementResult::NoHit;
        SetPreviewVisible(false);
        return;
    }

    // 사거리 제한: 캐릭터에서 조각의 가장 먼 모서리까지의 거리로 판정한다.
    const float MaxReach = BuildRangeCm + SelectedDefinition->ExtentCm.Size();
    if (FVector::Dist(Pawn->GetActorLocation(), SnapLocation) > MaxReach)
    {
        bHasCachedTarget = false;
        LastResult = EPlacementResult::OutOfRange;
        SetPreviewVisible(false);
        return;
    }

    PreviewMesh->SetWorldLocationAndRotation(SnapLocation, SnapRotation);
    SetPreviewVisible(true);

    CachedLocation = SnapLocation;
    CachedRotation = SnapRotation;
    CachedSupportPieceId = SupportPieceId;
    bHasCachedTarget = true;

    // 로컬 검증: 서버와 같은 함수를 써서 피드백이 어긋나지 않는다.
    if (const ABuildManager* Manager = GetBuildManager())
    {
        LastResult = Manager->ValidatePlacement(SelectedDefinition, SnapLocation, SnapRotation, FGuid(), Pawn);
    }
    else
    {
        LastResult = EPlacementResult::InvalidDefinition;
    }

    ApplyPreviewTint(LastResult);
}

void UBuildSystemComponent::ApplyPreviewTint(EPlacementResult Result)
{
    if (!PreviewMesh)
    {
        return;
    }

    if (!PreviewMID && PreviewMaterialBase)
    {
        PreviewMID = PreviewMesh->CreateDynamicMaterialInstance(0, PreviewMaterialBase);
    }

    if (PreviewMID)
    {
        const FLinearColor Tint = (Result == EPlacementResult::Valid) ? ValidTint : InvalidTint;
        PreviewMID->SetVectorParameterValue(TEXT("Tint"), Tint);
        return;
    }

    // 머티리얼이 없으면 렌더 커스텀 깊이로 유효/무효를 구분한다.
    PreviewMesh->SetRenderCustomDepth(Result != EPlacementResult::Valid);
}

bool UBuildSystemComponent::TryPlace()
{
    if (!SelectedDefinition || !bHasCachedTarget || LastResult != EPlacementResult::Valid)
    {
        return false;
    }

    if (AActor* Owner = GetOwner())
    {
        if (Owner->HasAuthority())
        {
            ABuildManager* Manager = GetBuildManager();
            return Manager
                && Manager->PlacePiece(SelectedDefinition, CachedLocation, CachedRotation, CachedSupportPieceId, GetOwningPawn()) != nullptr;
        }
    }

    // 클라이언트: 서버에 요청만 한다. 실제 스폰은 서버가 한다(복제로 다른 클라이언트에 전파).
    Server_RequestPlace(SelectedDefinition, CachedLocation, CachedRotation, CachedSupportPieceId);
    bHasCachedTarget = false;
    return true;
}

void UBuildSystemComponent::Server_RequestPlace_Implementation(UBuildPieceDefinition* Definition, FVector Location,
                                                              FQuat Rotation, FGuid SupportPieceId)
{
    ABuildManager* Manager = GetBuildManager();
    APawn* Pawn = GetOwningPawn();
    if (!Manager || !Pawn || !Definition)
    {
        return;
    }

    // 서버 측 검증 1: 요청자가 사거리 안에 있는가(스푸핑 방지).
    const float MaxReach = BuildRangeCm + Definition->ExtentCm.Size() + 100.f;
    if (FVector::Dist(Pawn->GetActorLocation(), Location) > MaxReach)
    {
        Client_PlacementRejected(EPlacementResult::OutOfRange);
        return;
    }

    // 서버 측 검증 2: 배치 타당성. 실패하면 클라이언트에 사유를 알린다.
    const EPlacementResult Result = Manager->ValidatePlacement(Definition, Location, Rotation, FGuid(), Pawn);
    if (Result != EPlacementResult::Valid)
    {
        Client_PlacementRejected(Result);
        return;
    }

    Manager->PlacePiece(Definition, Location, Rotation, SupportPieceId, Pawn);
}

void UBuildSystemComponent::Client_PlacementRejected_Implementation(EPlacementResult Result)
{
    LastResult = Result;
    OnPlacementRejected(Result);
}
