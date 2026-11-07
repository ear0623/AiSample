// Copyright (c) 2026. Example code for the Unreal character customization guide.
//
// ModularCharacter.h
//   부위별 스켈레탈 메시(모듈러 의상)를 리더 포즈로 묶고, 런타임에 교체·색상·모프·바디 마스킹을
//   적용하는 캐릭터. 외형 데이터(FCharacterCustomizationData)는 서버 권위로 복제된다.
//
//   설계 원칙
//   - 몸(GetMesh())이 리더, 의상 컴포넌트는 팔로어(SetLeaderPoseComponent). 애니메이션 평가는 1회.
//   - 메시는 ItemId로 해석하고 비동기 로드한다(동기 로드는 히치).
//   - 색·모프·마스킹은 모두 MID/파라미터 경유(원본 머티리얼·메시 불변).
//   - 클라이언트는 즉시 반영 → 서버 판정 → OnRep으로 보정.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "CharacterCustomizationTypes.h"
#include "ModularCharacter.generated.h"

class UMaterialInstanceDynamic;
class USkeletalMesh;

/**
 * 모듈러 캐릭터.
 * 컴포넌트 구성: Mesh(몸, 리더) + Head/Torso/Legs/Hands/Feet/Back(팔로어)
 */
UCLASS(Blueprintable)
class MYGAME_API AModularCharacter : public ACharacter
{
    GENERATED_BODY()

public:
    explicit AModularCharacter(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get());

    // -----------------------------------------------------------------------
    // 컴포넌트
    // -----------------------------------------------------------------------

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Modular|Components")
    TObjectPtr<USkeletalMeshComponent> HeadMesh;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Modular|Components")
    TObjectPtr<USkeletalMeshComponent> TorsoMesh;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Modular|Components")
    TObjectPtr<USkeletalMeshComponent> LegsMesh;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Modular|Components")
    TObjectPtr<USkeletalMeshComponent> HandsMesh;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Modular|Components")
    TObjectPtr<USkeletalMeshComponent> FeetMesh;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Modular|Components")
    TObjectPtr<USkeletalMeshComponent> BackMesh;

    // -----------------------------------------------------------------------
    // 상태
    // -----------------------------------------------------------------------

    /** 서버가 소유하는 외형 데이터. 변경 시 OnRep이 전체 외형을 다시 적용한다. */
    UPROPERTY(ReplicatedUsing = OnRep_Customization, BlueprintReadOnly, Category = "Modular|State")
    FCharacterCustomizationData Customization;

    // -----------------------------------------------------------------------
    // 조회
    // -----------------------------------------------------------------------

    UFUNCTION(BlueprintPure, Category = "Modular")
    USkeletalMeshComponent* GetMeshForSlot(EClothingSlot Slot) const;

    /** 복사 없이 읽기 위한 접근자(블루프린트 노출 없음). */
    const FCharacterCustomizationData& GetCustomization() const { return Customization; }

    // -----------------------------------------------------------------------
    // 적용
    // -----------------------------------------------------------------------

    /** 외형 데이터 전체를 적용한다(메시 해석 → 색 → 모프 → 마스크). */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    void ApplyCustomization(const FCharacterCustomizationData& NewData);

    /** 슬롯에 메시를 장착한다. 아직 로드되지 않았으면 비동기 로드 후 적용한다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    void EquipMesh(EClothingSlot Slot, TSoftObjectPtr<USkeletalMesh> Mesh, bool bHideBodyUnderneath = true);

    /** 슬롯을 비운다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    void ClearSlot(EClothingSlot Slot);

    /** 모프 가중치를 설정하고 상태에 기록한다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    bool SetMorphTargetWeight(FName MorphName, float Weight);

    /** 슬롯의 머티리얼 색 파라미터를 설정한다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    bool SetColorParameter(EClothingSlot Slot, FName ParameterName, FLinearColor Value);

    /** 헤어 스타일 ID를 바꾼다. 실제 교체는 구현체(OnHairStyleChanged)가 한다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    void SetHairStyle(FName StyleId);

    /** 피부 색·주근깨·흉터 파라미터를 몸 머티리얼에 적용한다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    void ApplySkinParameters(const FCharacterCustomizationData& Data);

    /** 장착 상태에 맞춰 몸의 가림 마스크 파라미터를 갱신한다. */
    UFUNCTION(BlueprintCallable, Category = "Modular")
    void UpdateBodyMask();

    /** 클라이언트가 서버에 외형을 요청한다. 서버가 검증·저장한다. */
    UFUNCTION(Server, Reliable)
    void ServerSetCustomization(const FCharacterCustomizationData& NewData);

    /** 이 캐릭터의 외형을 지금 바꿀 수 있는가(서버 또는 로컬 소유자). */
    UFUNCTION(BlueprintPure, Category = "Modular")
    bool CanModifyCustomization() const;

protected:
    // -----------------------------------------------------------------------
    // AActor / ACharacter
    // -----------------------------------------------------------------------

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

    /** 복제 수신 시 전체 외형 재적용. */
    UFUNCTION()
    void OnRep_Customization();

    // -----------------------------------------------------------------------
    // 내부 처리
    // -----------------------------------------------------------------------

    /** 모든 팔로어를 몸(리더)에 연결한다. BeginPlay에서 1회. */
    void InitializeLeaderPose();

    /** 팔로어의 LOD 동기·바운즈·그림자·콜리전 설정을 통일한다. */
    void UpdateFollowerSettings(USkeletalMeshComponent* Follower) const;

    /** 상태의 모프 가중치를 몸과 팔로어에 적용한다. */
    void ApplyMorphTargets();

    /**
     * 팔로어의 모프 커브 컨테이너는 매 프레임 초기화되므로 주기적으로 재적용한다.
     * (가이드 3.2절: 리더의 morph/material 커브만 팔로어로 복사된다)
     */
    void RefreshFollowerMorphs();

    /** 로드된 메시를 컴포넌트에 실제로 적용한다. */
    void ApplySlotMesh(EClothingSlot Slot, USkeletalMesh* Mesh);

    /** 비동기 로드 완료 콜백. */
    void OnSlotMeshLoaded(EClothingSlot Slot, FSoftObjectPath Path);

    /** 슬롯 상태를 얻거나 새로 만든다. */
    FClothingSlotState& GetOrAddSlotState(EClothingSlot Slot);

    /** 컴포넌트의 머티리얼 인덱스에 대한 MID를 얻는다(이미 MID면 그대로 재사용). */
    UMaterialInstanceDynamic* GetOrCreateSlotMID(USkeletalMeshComponent* TargetComp, int32 MaterialIndex);

    /** 헤어 교체 훅. Groom 모듈 의존을 예제에서 분리하기 위해 이벤트로 위임한다. */
    UFUNCTION(BlueprintImplementableEvent, Category = "Modular")
    void OnHairStyleChanged(FName StyleId);

    /** 외형 적용 완료 통지(UI·세이브·통계). */
    UFUNCTION(BlueprintImplementableEvent, Category = "Modular")
    void OnCustomizationApplied();

protected:
    /** 팔로어 모프를 매 프레임 재적용할지. 애님 커브로 처리하면 끈다. */
    UPROPERTY(EditDefaultsOnly, Category = "Modular|Performance")
    bool bRefreshFollowerMorphs = true;

    /** 팔로어 모프 재적용 주기(초). 0이면 매 프레임. */
    UPROPERTY(EditDefaultsOnly, Category = "Modular|Performance", meta = (ClampMin = "0.0"))
    float FollowerMorphRefreshInterval = 0.f;

private:
    /** BeginPlay에서 수집한 팔로어 컴포넌트 목록. */
    UPROPERTY(Transient)
    TArray<TObjectPtr<USkeletalMeshComponent>> FollowerMeshes;

    /** 슬롯별 마지막 비동기 요청 경로. 경쟁 조건(늦게 도착한 콜백)을 걸러낸다. */
    UPROPERTY(Transient)
    TMap<EClothingSlot, FSoftObjectPath> PendingLoads;

    float MorphRefreshAccumulator = 0.f;
};
