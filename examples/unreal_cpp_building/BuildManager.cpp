// Copyright (c) 2026. Example code for the open world architecture guide (in-game building).
//
// BuildManager.cpp

#include "BuildManager.h"

#include "BuildingTypes.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Net/UnrealNetwork.h"

// ---------------------------------------------------------------------------
// ABuildPieceActor
// ---------------------------------------------------------------------------

ABuildPieceActor::ABuildPieceActor(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    bReplicates = true;
    SetReplicateMovement(false);   // 건축물은 설치 후 움직이지 않는다.
    SetCanBeDamaged(true);

    MeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("PieceMesh"));
    RootComponent = MeshComponent;

    // 건축 조각 전용 오브젝트 채널(프로젝트 설정에서 "BuildPiece"로 이름 붙인다).
    // 배치 겹침 검사에서 이 채널을 제외해야 이웃 조각끼리 맞대어 놓을 수 있다.
    MeshComponent->SetCollisionObjectType(ECC_GameTraceChannel1);
    MeshComponent->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
    MeshComponent->SetCollisionResponseToAllChannels(ECR_Block);
    MeshComponent->SetCanEverAffectNavigation(true);
}

void ABuildPieceActor::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);

    DOREPLIFETIME(ABuildPieceActor, PieceId);
    DOREPLIFETIME(ABuildPieceActor, Definition);
}

void ABuildPieceActor::InitializePiece(UBuildPieceDefinition* InDefinition, const FGuid& InPieceId)
{
    Definition = InDefinition;
    PieceId = InPieceId;

    // 서버에서는 즉시 시각·충돌을 구성하고, 클라이언트는 OnRep_Definition에서 같은 일을 한다.
    ApplyDefinitionVisuals();
}

void ABuildPieceActor::OnRep_Definition()
{
    ApplyDefinitionVisuals();
}

void ABuildPieceActor::ApplyDefinitionVisuals()
{
    if (!Definition || !MeshComponent)
    {
        return;
    }

    // 작은 조각 메시는 동기 로드해도 무리가 없다. 큰 구조물이면 비동기 + 프록시 메시를 쓴다.
    if (UStaticMesh* LoadedMesh = Definition->Mesh.LoadSynchronous())
    {
        MeshComponent->SetStaticMesh(LoadedMesh);
    }
}

FBox ABuildPieceActor::GetBuildBounds() const
{
    if (!Definition)
    {
        return FBox(GetActorLocation(), GetActorLocation());
    }

    const FVector Extent = Definition->ExtentCm;
    const FTransform Transform = GetActorTransform();

    FBox Bounds(ForceInit);
    for (int32 CornerIndex = 0; CornerIndex < 8; ++CornerIndex)
    {
        const FVector Corner(
            (CornerIndex & 1) ? Extent.X : -Extent.X,
            (CornerIndex & 2) ? Extent.Y : -Extent.Y,
            (CornerIndex & 4) ? Extent.Z : -Extent.Z);

        Bounds += Transform.TransformPosition(Corner);
    }

    return Bounds;
}

// ---------------------------------------------------------------------------
// ABuildManager
// ---------------------------------------------------------------------------

ABuildManager::ABuildManager(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    bReplicates = true;
    PrimaryActorTick.bCanEverTick = false;

    USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    RootComponent = Root;

    PieceActorClass = ABuildPieceActor::StaticClass();
}

void ABuildManager::BeginPlay()
{
    Super::BeginPlay();

    PieceLookup.Reset();
    for (ABuildPieceActor* Piece : Pieces)
    {
        if (Piece)
        {
            PieceLookup.Add(Piece->PieceId, Piece);
        }
    }
}

ABuildPieceActor* ABuildManager::FindPiece(const FGuid& PieceId) const
{
    const TWeakObjectPtr<ABuildPieceActor>* Found = PieceLookup.Find(PieceId);
    return Found ? Found->Get() : nullptr;
}

bool ABuildManager::ArePiecesConnected(const ABuildPieceActor* A, const ABuildPieceActor* B) const
{
    if (!A || !B)
    {
        return false;
    }

    return A->GetBuildBounds().ExpandBy(SupportLinkGapCm)
        .Intersect(B->GetBuildBounds().ExpandBy(SupportLinkGapCm));
}

bool ABuildManager::HasSupportNear(const UBuildPieceDefinition* Definition, const FVector& Location, const FQuat& Rotation,
                                  const FGuid& IgnorePieceId, FGuid& OutSupportPieceId) const
{
    if (!Definition)
    {
        return false;
    }

    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }

    // 뿌리 조각(기초·바닥)은 지면에 닿아야 한다.
    if (Definition->bIsRoot)
    {
        const FVector Start = Location - FVector(0.f, 0.f, Definition->ExtentCm.Z);
        const FVector End = Start - FVector(0.f, 0.f, 50.f);

        FCollisionQueryParams Params(SCENE_QUERY_STAT(BuildGroundCheck), false, this);
        FHitResult Hit;
        return World->LineTraceSingleByChannel(Hit, Start, End, ECC_WorldStatic, Params);
    }

    // 그 외 조각: 아래쪽에 있는 기존 조각의 지지 범위 안에 들어와야 한다.
    const FBox QueryBox = FBox::BuildAABB(Location, Definition->ExtentCm).ExpandBy(SupportLinkGapCm);

    for (const ABuildPieceActor* Piece : Pieces)
    {
        if (!Piece || Piece->PieceId == IgnorePieceId)
        {
            continue;
        }

        // 위에 얹히는 조각을 지지로 오인하지 않도록, 자신보다 높은 조각은 제외한다.
        if (Piece->GetActorLocation().Z > Location.Z + 1.f)
        {
            continue;
        }

        if (Piece->GetBuildBounds().ExpandBy(SupportLinkGapCm).Intersect(QueryBox))
        {
            OutSupportPieceId = Piece->PieceId;
            return true;
        }
    }

    return false;
}

EPlacementResult ABuildManager::ValidatePlacement(const UBuildPieceDefinition* Definition, const FVector& Location,
                                                 const FQuat& Rotation, const FGuid& IgnorePieceId,
                                                 const APawn* InstigatorPawn) const
{
    UWorld* World = GetWorld();
    if (!World || !Definition)
    {
        return EPlacementResult::InvalidDefinition;
    }

    // 1) 수직 정렬: 조각의 up 벡터가 지면 법선에서 25도 이상 벗어나면 배치 불가.
    const float UpDot = Rotation.GetUpVector().Z;
    if (UpDot < FMath::Cos(FMath::DegreesToRadians(25.f)))
    {
        return EPlacementResult::TooSteep;
    }

    // 2) 겹침: 98 % 크기로 검사해 이웃 조각과의 접촉(맞댐)은 허용한다.
    //    건축 조각(ECC_GameTraceChannel1)은 검사 대상에서 제외한다.
    FCollisionQueryParams Params(SCENE_QUERY_STAT(BuildPlacement), false, this);
    if (InstigatorPawn)
    {
        Params.AddIgnoredActor(InstigatorPawn);
    }
    if (const ABuildPieceActor* Ignored = FindPiece(IgnorePieceId))
    {
        Params.AddIgnoredActor(Ignored);
    }

    FCollisionObjectQueryParams ObjectParams;
    ObjectParams.AddObjectTypesToQuery(ECC_WorldStatic);
    ObjectParams.AddObjectTypesToQuery(ECC_WorldDynamic);
    ObjectParams.AddObjectTypesToQuery(ECC_Pawn);

    const FCollisionShape Shape = FCollisionShape::MakeBox(Definition->ExtentCm * 0.98f);
    if (World->OverlapBlockingTestWithParams(Location, Rotation, Shape, Params, ObjectParams))
    {
        return EPlacementResult::Overlapping;
    }

    // 3) 지지: 기초(뿌리) 또는 아래쪽 구조물이 있어야 한다.
    if (Definition->bRequiresSupport)
    {
        FGuid SupportPieceId;
        if (!HasSupportNear(Definition, Location, Rotation, IgnorePieceId, SupportPieceId))
        {
            return EPlacementResult::NoSupport;
        }
    }

    return EPlacementResult::Valid;
}

ABuildPieceActor* ABuildManager::PlacePiece(UBuildPieceDefinition* Definition, const FVector& Location, const FQuat& Rotation,
                                            const FGuid& SupportPieceId, APawn* InstigatorPawn)
{
    UWorld* World = GetWorld();
    if (!HasAuthority() || !World || !Definition)
    {
        return nullptr;
    }

    // 서버 재검증: 클라이언트 프리뷰를 신뢰하지 않는다.
    if (ValidatePlacement(Definition, Location, Rotation, FGuid(), InstigatorPawn) != EPlacementResult::Valid)
    {
        return nullptr;
    }

    const TSubclassOf<ABuildPieceActor> SpawnClass = PieceActorClass ? PieceActorClass : ABuildPieceActor::StaticClass();

    FActorSpawnParameters SpawnParams;
    SpawnParams.Owner = this;
    SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

    ABuildPieceActor* Piece = World->SpawnActor<ABuildPieceActor>(SpawnClass, Location, Rotation.Rotator(), SpawnParams);
    if (!Piece)
    {
        return nullptr;
    }

    Piece->SetActorRotation(Rotation);   // Rotator 변환에서 잃는 축을 보존한다.
    Piece->InitializePiece(Definition, FGuid::NewGuid());

    Pieces.Add(Piece);
    PieceLookup.Add(Piece->PieceId, Piece);

    RecomputeIntegrity();

    return Piece;
}

bool ABuildManager::RemovePiece(const FGuid& PieceId)
{
    if (!HasAuthority())
    {
        return false;
    }

    ABuildPieceActor* Piece = FindPiece(PieceId);
    if (!Piece)
    {
        return false;
    }

    Pieces.Remove(Piece);
    PieceLookup.Remove(PieceId);
    Piece->Destroy();

    // 지지 구조가 바뀌었으므로 위쪽 구조물이 무너질 수 있다.
    RecomputeIntegrity();

    return true;
}

void ABuildManager::RecomputeIntegrity(int32 Pass)
{
    if (!HasAuthority() || Pass >= MaxIntegrityPasses)
    {
        return;
    }

    // 1) 지면에 붙은 뿌리에서 BFS로 지지 가능한 집합을 구한다.
    TArray<ABuildPieceActor*> Queue;
    TSet<ABuildPieceActor*> Reachable;
    TMap<ABuildPieceActor*, ABuildPieceActor*> Parent;

    for (ABuildPieceActor* Piece : Pieces)
    {
        if (Piece && Piece->Definition && Piece->Definition->bIsRoot)
        {
            Reachable.Add(Piece);
            Queue.Add(Piece);
        }
    }

    int32 Head = 0;
    while (Head < Queue.Num())
    {
        ABuildPieceActor* Current = Queue[Head++];

        for (ABuildPieceActor* Candidate : Pieces)
        {
            if (!Candidate || Reachable.Contains(Candidate))
            {
                continue;
            }

            if (ArePiecesConnected(Current, Candidate))
            {
                Reachable.Add(Candidate);
                Queue.Add(Candidate);
                Parent.Add(Candidate, Current);
            }
        }
    }

    // 2) 뿌리와 연결되지 않은 조각은 붕괴한다.
    TArray<ABuildPieceActor*> Collapse;
    for (ABuildPieceActor* Piece : Pieces)
    {
        if (Piece && !Reachable.Contains(Piece))
        {
            Collapse.AddUnique(Piece);
        }
    }

    // 3) 하중 전파: 잎에서 뿌리로 지지 비용을 누적한다.
    TMap<ABuildPieceActor*, int32> Load;
    for (ABuildPieceActor* Piece : Pieces)
    {
        if (Piece && Piece->Definition)
        {
            Load.Add(Piece, Piece->Definition->SupportCost);
        }
    }

    for (int32 Index = Queue.Num() - 1; Index >= 0; --Index)
    {
        ABuildPieceActor* Piece = Queue[Index];
        ABuildPieceActor* const* ParentPtr = Parent.Find(Piece);
        if (!ParentPtr || !*ParentPtr)
        {
            continue;
        }

        int32* ParentLoad = Load.Find(*ParentPtr);
        const int32* OwnLoad = Load.Find(Piece);
        if (ParentLoad && OwnLoad)
        {
            *ParentLoad += *OwnLoad;
        }
    }

    // 4) 뿌리 용량을 넘은 트리는 붕괴한다(간단화: 뿌리부터 잎까지 통째로).
    //    실무에서는 붕괴 연출을 위해 위쪽 절반만 떨어뜨리는 식으로 다듬는다.
    for (ABuildPieceActor* Root : Pieces)
    {
        if (!Root || !Root->Definition || !Root->Definition->bIsRoot)
        {
            continue;
        }

        const int32 RootLoad = Load.FindRef(Root);
        if (RootLoad <= Root->Definition->SupportCapacity)
        {
            continue;
        }

        for (ABuildPieceActor* Piece : Pieces)
        {
            if (!Piece)
            {
                continue;
            }

            ABuildPieceActor* Walk = Piece;
            int32 Guard = 0;
            while (Walk && Guard++ < 128)
            {
                if (Walk == Root)
                {
                    Collapse.AddUnique(Piece);
                    break;
                }

                ABuildPieceActor* const* Next = Parent.Find(Walk);
                if (!Next)
                {
                    break;
                }
                Walk = *Next;
            }
        }
    }

    if (Collapse.Num() == 0)
    {
        return;
    }

    // 5) 제거하고, 남은 구조를 다시 검사한다(연쇄 붕괴).
    for (ABuildPieceActor* Piece : Collapse)
    {
        if (!Piece)
        {
            continue;
        }

        Pieces.Remove(Piece);
        PieceLookup.Remove(Piece->PieceId);
        Piece->Destroy();
    }

    RecomputeIntegrity(Pass + 1);
}
