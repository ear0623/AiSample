// Copyright (c) 2026. Example code for the open world architecture guide (in-game building).
//
// BuildSystemComponent.h
//   플레이어 측 인게임 건축 입력·프리뷰.
//   - 고스트(홀로그램) 프리뷰 메시와 유효/무효 색상
//   - 소켓 스냅 → 그리드 스냅 우선순위
//   - 로컬 검증(즉시 피드백) + 서버 요청(RPC, 서버가 최종 판정)

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "BuildingTypes.h"
#include "BuildSystemComponent.generated.h"

class ABuildManager;
class ABuildPieceActor;
class UBuildPieceDefinition;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UStaticMeshComponent;

UCLASS(ClassGroup = (Build), meta = (BlueprintSpawnableComponent))
class MYGAME_API UBuildSystemComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    explicit UBuildSystemComponent(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

    /** 건축 모드 진입. 조각 정의를 고른 뒤 호출한다. */
    UFUNCTION(BlueprintCallable, Category = "Build")
    void StartPreview(UBuildPieceDefinition* Definition);

    UFUNCTION(BlueprintCallable, Category = "Build")
    void CancelPreview();

    /** 현재 프리뷰 위치에 배치를 요청한다. 서버 판정 결과는 Client_PlacementRejected로 돌아온다. */
    UFUNCTION(BlueprintCallable, Category = "Build")
    bool TryPlace();

    UFUNCTION(BlueprintPure, Category = "Build")
    EPlacementResult GetLastPlacementResult() const { return LastResult; }

    UFUNCTION(BlueprintPure, Category = "Build")
    bool IsPreviewActive() const { return SelectedDefinition != nullptr; }

    /** 서버가 거부했을 때(UI 사운드·문구). */
    UFUNCTION(BlueprintImplementableEvent, Category = "Build")
    void OnPlacementRejected(EPlacementResult Result);

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

    /** 프리뷰 트랜스폼을 갱신하고 유효성을 재평가한다. */
    void UpdatePreview();

    /**
     * 스냅 트랜스폼 계산.
     *  ① 기존 조각의 소켓과 내 조각의 대응 소켓을 맞춘다(정밀).
     *  ② 실패하면 표면 히트 지점을 그리드로 내리고 요(yaw)를 90도 단위로 맞춘다.
     */
    bool ComputeSnapTransform(const FHitResult& Hit, FVector& OutLocation, FQuat& OutRotation, FGuid& OutSupportPieceId) const;

    void ApplyPreviewTint(EPlacementResult Result);
    void SetPreviewVisible(bool bVisible);

    ABuildManager* GetBuildManager() const;
    APawn* GetOwningPawn() const;

    /** 서버에 배치를 요청한다(소유 클라이언트 → 서버). */
    UFUNCTION(Server, Reliable)
    void Server_RequestPlace(UBuildPieceDefinition* Definition, FVector Location, FQuat Rotation, FGuid SupportPieceId);

    /** 서버가 거부했음을 알린다. */
    UFUNCTION(Client, Reliable)
    void Client_PlacementRejected(EPlacementResult Result);

protected:
    UPROPERTY(EditDefaultsOnly, Category = "Build")
    float BuildRangeCm = 600.f;

    UPROPERTY(EditDefaultsOnly, Category = "Build")
    float GridCm = 100.f;

    /** 프리뷰 색을 바꿀 머티리얼(파라미터 "Tint"). */
    UPROPERTY(EditDefaultsOnly, Category = "Build")
    TObjectPtr<UMaterialInterface> PreviewMaterialBase;

    UPROPERTY(EditDefaultsOnly, Category = "Build")
    FLinearColor ValidTint = FLinearColor(0.1f, 0.9f, 0.25f, 0.45f);

    UPROPERTY(EditDefaultsOnly, Category = "Build")
    FLinearColor InvalidTint = FLinearColor(0.95f, 0.15f, 0.1f, 0.45f);

private:
    UPROPERTY(Transient)
    TObjectPtr<UBuildPieceDefinition> SelectedDefinition;

    UPROPERTY(Transient)
    TObjectPtr<UStaticMeshComponent> PreviewMesh;

    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> PreviewMID;

    UPROPERTY(Transient)
    TObjectPtr<ABuildManager> CachedManager;

    EPlacementResult LastResult = EPlacementResult::NoHit;

    FVector CachedLocation = FVector::ZeroVector;
    FQuat CachedRotation = FQuat::Identity;
    FGuid CachedSupportPieceId;
    bool bHasCachedTarget = false;
};
