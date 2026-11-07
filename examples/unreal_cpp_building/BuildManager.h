// Copyright (c) 2026. Example code for the open world architecture guide (in-game building).
//
// BuildManager.h
//   인게임 건축의 서버 권위 부분.
//   - 조각 액터(ABuildPieceActor): 스폰되는 구조물 1개
//   - 관리자(ABuildManager): 배치 검증, 스폰, 구조 안정성(지지 그래프) 계산, 붕괴

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "BuildingTypes.h"
#include "BuildManager.generated.h"

class UBuildPieceDefinition;
class UStaticMeshComponent;

/** 배치된 구조물 1개. 서버에서 스폰되고 복제로 클라이언트에 나타난다. */
UCLASS(Blueprintable)
class MYGAME_API ABuildPieceActor : public AActor
{
    GENERATED_BODY()

public:
    explicit ABuildPieceActor(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

    /** 서버에서만 호출. 정의에 따라 메시·충돌·태그를 설정한다. */
    void InitializePiece(UBuildPieceDefinition* InDefinition, const FGuid& InPieceId);

    UFUNCTION(BlueprintPure, Category = "Build")
    FBox GetBuildBounds() const;

    UFUNCTION(BlueprintPure, Category = "Build")
    UStaticMeshComponent* GetMeshComponent() const { return MeshComponent; }

    /** 메시를 할당한다. 서버는 초기화 시, 클라이언트는 복제 수신 시 호출한다. */
    void ApplyDefinitionVisuals();

    UPROPERTY(BlueprintReadOnly, Replicated, Category = "Build")
    FGuid PieceId;

    UPROPERTY(BlueprintReadOnly, ReplicatedUsing = OnRep_Definition, Category = "Build")
    TObjectPtr<UBuildPieceDefinition> Definition;

protected:
    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

    UFUNCTION()
    void OnRep_Definition();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Build")
    TObjectPtr<UStaticMeshComponent> MeshComponent;
};

/**
 * 건축 관리자. 레벨에 1개(또는 월드 파티션 셀마다 1개) 배치한다.
 * 모든 배치·삭제 판정과 지지 그래프는 서버에서만 계산한다.
 */
UCLASS(Blueprintable)
class MYGAME_API ABuildManager : public AActor
{
    GENERATED_BODY()

public:
    explicit ABuildManager(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

    /** 서버 전용. 검증 통과 시 조각을 스폰하고 지지 그래프를 갱신한다. */
    ABuildPieceActor* PlacePiece(UBuildPieceDefinition* Definition, const FVector& Location, const FQuat& Rotation,
                                 const FGuid& SupportPieceId, APawn* InstigatorPawn);

    /** 서버 전용. 조각을 제거하고 남은 구조를 재검사한다. */
    bool RemovePiece(const FGuid& PieceId);

    /** 겹침·지지·경사를 검사한다. 프리뷰(클라이언트)와 서버가 같은 함수를 쓴다. */
    EPlacementResult ValidatePlacement(const UBuildPieceDefinition* Definition, const FVector& Location,
                                       const FQuat& Rotation, const FGuid& IgnorePieceId,
                                       const APawn* InstigatorPawn) const;

    UFUNCTION(BlueprintPure, Category = "Build")
    ABuildPieceActor* FindPiece(const FGuid& PieceId) const;

    UFUNCTION(BlueprintPure, Category = "Build")
    int32 GetPieceCount() const { return Pieces.Num(); }

protected:
    virtual void BeginPlay() override;

    /** 지지 그래프를 다시 계산하고, 지지되지 않는 조각을 붕괴시킨다. */
    void RecomputeIntegrity(int32 Pass = 0);

    bool ArePiecesConnected(const ABuildPieceActor* A, const ABuildPieceActor* B) const;

    /** 조각이 지지 기반(기초·지면에 닿은 조각)과 연결될 수 있는 위치인가. */
    bool HasSupportNear(const UBuildPieceDefinition* Definition, const FVector& Location, const FQuat& Rotation,
                        const FGuid& IgnorePieceId, FGuid& OutSupportPieceId) const;

    UPROPERTY(Transient)
    TArray<TObjectPtr<ABuildPieceActor>> Pieces;

    UPROPERTY(EditDefaultsOnly, Category = "Build")
    TSubclassOf<ABuildPieceActor> PieceActorClass;

    /** 조각 사이의 지지 연결로 인정하는 최대 틈(cm). */
    UPROPERTY(EditDefaultsOnly, Category = "Build", meta = (ClampMin = "0.0"))
    float SupportLinkGapCm = 25.f;

    /** 붕괴 재검사 최대 횟수(연쇄 붕괴 대비). */
    UPROPERTY(EditDefaultsOnly, Category = "Build", meta = (ClampMin = "1"))
    int32 MaxIntegrityPasses = 4;

private:
    TMap<FGuid, TWeakObjectPtr<ABuildPieceActor>> PieceLookup;
    bool bRecomputing = false;
};
