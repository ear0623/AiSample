// Copyright (c) 2026. Example code for the Unreal character customization guide.
//
// CharacterCustomizationTypes.h
//   캐릭터 외형 커스터마이징의 데이터 계약(enum / struct / 직렬화 / 복제)만 담는다.
//   - 메시·머티리얼을 직접 만지지 않는다(그 책임은 AModularCharacter).
//   - 저장(SaveGame)과 네트워크(NetSerialize)가 같은 구조를 공유한다.
//   - 로컬 전용 데이터(로드된 메시 포인터)는 Transient로 분리해 복제 대상에서 뺀다.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "UObject/PrimaryAssetId.h"
#include "CharacterCustomizationTypes.generated.h"

class USkeletalMesh;

/** 의상 슬롯. 게임의 장비 부위와 1:1로 맞춘다. */
UENUM(BlueprintType)
enum class EClothingSlot : uint8
{
    Head    UMETA(DisplayName = "Head"),
    Torso   UMETA(DisplayName = "Torso"),
    Legs    UMETA(DisplayName = "Legs"),
    Hands   UMETA(DisplayName = "Hands"),
    Feet    UMETA(DisplayName = "Feet"),
    Back    UMETA(DisplayName = "Back"),

    /** 배열 크기 계산용. 실제 슬롯이 아니다. */
    Count   UMETA(Hidden)
};

/**
 * 의상 아이템 정의. AssetManager가 Directories를 스캔해 PrimaryAssetId로 해석한다.
 * 복제·저장에는 이 정의의 ID만 쓰고, 메시는 각 클라이언트가 해석한다.
 */
UCLASS(BlueprintType)
class MYGAME_API UClothingItemDefinition : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Clothing")
    EClothingSlot Slot = EClothingSlot::Torso;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Clothing")
    TSoftObjectPtr<USkeletalMesh> Mesh;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Clothing")
    FText DisplayName;

    /** 이 아이템이 몸의 해당 부위를 가리는가. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Clothing")
    bool bHideBodyUnderneath = true;

    virtual FPrimaryAssetId GetPrimaryAssetId() const override
    {
        return FPrimaryAssetId(TEXT("ClothingItem"), GetFName());
    }
};

/** 슬롯 하나에 적용할 머티리얼 색 파라미터. */
USTRUCT(BlueprintType)
struct FClothingColorParameter
{
    GENERATED_BODY()

    /** 머티리얼 파라미터 이름. 예: "FabricTint", "TrimTint" */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FName ParameterName;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FLinearColor Value = FLinearColor::White;

    FClothingColorParameter() = default;

    FClothingColorParameter(FName InName, const FLinearColor& InValue)
        : ParameterName(InName)
        , Value(InValue)
    {
    }
};

/** 모프 타깃(블렌드셰이프) 하나의 가중치. 얼굴·체형에 쓴다. */
USTRUCT(BlueprintType)
struct FCharacterMorphTarget
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FName Name;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization", meta = (ClampMin = "0.0", ClampMax = "1.0"))
    float Weight = 0.f;
};

/** 슬롯 하나의 현재 상태. 메시는 로컬에서만 해석한다(복제하지 않는다). */
USTRUCT(BlueprintType)
struct FClothingSlotState
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    EClothingSlot Slot = EClothingSlot::Torso;

    /** 복제·저장의 기준 키. 메시 경로를 직접 복제하지 않는다. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FPrimaryAssetId ItemId;

    /** ItemId로 해석한 메시. 클라이언트마다 다르게 채워지는 로컬 캐시. */
    UPROPERTY(Transient)
    TSoftObjectPtr<USkeletalMesh> ResolvedMesh;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    TArray<FClothingColorParameter> Colors;

    /** 이 슬롯이 몸의 해당 부위를 가리는가(바디 마스킹). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    bool bHideBodyUnderneath = true;

    bool IsEquipped() const { return !ResolvedMesh.IsNull(); }

    bool NetSerialize(FArchive& Ar, class UPackageMap* Map, bool& bOutSuccess);
};

/**
 * 캐릭터 하나의 전체 외형.
 *  - 이산 값: 슬롯별 ItemId, 헤어 스타일 ID
 *  - 연속 값: 모프 가중치, 색, 스케일, 피부 파라미터
 *  - 로컬 값: ResolvedMesh(Transient)
 * 저장과 복제가 이 구조 하나를 공유한다.
 */
USTRUCT(BlueprintType)
struct FCharacterCustomizationData
{
    GENERATED_BODY()

    // ---------- 의상 ----------
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    TArray<FClothingSlotState> Slots;

    // ---------- 얼굴·체형 ----------
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    TArray<FCharacterMorphTarget> MorphTargets;

    /** 0.85 ~ 1.15 범위. 캡슐 크기는 별도로 보정해야 한다(가이드 4.3절). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization", meta = (ClampMin = "0.85", ClampMax = "1.15"))
    float HeightScale = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization", meta = (ClampMin = "0.85", ClampMax = "1.15"))
    float LegLengthScale = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization", meta = (ClampMin = "0.85", ClampMax = "1.15"))
    float ShoulderWidthScale = 1.f;

    // ---------- 피부·헤어 ----------
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FClothingColorParameter SkinTint = FClothingColorParameter(TEXT("SkinTint"), FLinearColor::White);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FClothingColorParameter HairTint = FClothingColorParameter(TEXT("HairColor"), FLinearColor::Black);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization", meta = (ClampMin = "0.0", ClampMax = "1.0"))
    float FreckleAmount = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization", meta = (ClampMin = "0.0", ClampMax = "1.0"))
    float ScarAmount = 0.f;

    /** 헤어 스타일 ID. 실제 Groom/메시는 데이터 에셋이 해석한다. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FName HairStyleId;

    // ---------- 조회 ----------
    const FClothingSlotState* FindSlot(EClothingSlot InSlot) const
    {
        return Slots.FindByPredicate([InSlot](const FClothingSlotState& Entry)
        {
            return Entry.Slot == InSlot;
        });
    }

    FClothingSlotState* FindSlotMutable(EClothingSlot InSlot)
    {
        return Slots.FindByPredicate([InSlot](const FClothingSlotState& Entry)
        {
            return Entry.Slot == InSlot;
        });
    }

    void Reset()
    {
        Slots.Reset();
        MorphTargets.Reset();
        HeightScale = 1.f;
        LegLengthScale = 1.f;
        ShoulderWidthScale = 1.f;
        SkinTint = FClothingColorParameter(TEXT("SkinTint"), FLinearColor::White);
        HairTint = FClothingColorParameter(TEXT("HairColor"), FLinearColor::Black);
        FreckleAmount = 0.f;
        ScarAmount = 0.f;
        HairStyleId = NAME_None;
    }

    bool NetSerialize(FArchive& Ar, class UPackageMap* Map, bool& bOutSuccess);

    // ---------- 양자화 도우미 ----------
    // 네트워크에서 float(4 B)를 uint8(1 B)로 줄인다. 시각적 차이는 0.4 % 이하다.
    static uint8 QuantizeUnit(float InValue)
    {
        return static_cast<uint8>(FMath::Clamp(FMath::RoundToInt(InValue * 255.f), 0, 255));
    }

    static float DequantizeUnit(uint8 InValue)
    {
        return static_cast<float>(InValue) / 255.f;
    }

    static uint8 QuantizeRange(float InValue, float InMin, float InMax)
    {
        const float Alpha = (InMax - InMin) > KINDA_SMALL_NUMBER ? (InValue - InMin) / (InMax - InMin) : 0.f;
        return QuantizeUnit(Alpha);
    }

    static float DequantizeRange(uint8 InValue, float InMin, float InMax)
    {
        return FMath::Lerp(InMin, InMax, DequantizeUnit(InValue));
    }
};

/** 저장되는 프리셋(로드아웃) 하나. */
USTRUCT(BlueprintType)
struct FCharacterPreset
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FText DisplayName;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Customization")
    FCharacterCustomizationData Data;
};

// ---------------------------------------------------------------------------
// 복제 지원. NetSerialize를 구현한 USTRUCT는 이 traits 선언이 있어야
// 프로퍼티 복제와 RPC 파라미터에서 커스텀 직렬화가 호출된다.
// ---------------------------------------------------------------------------

template<>
struct TStructOpsTypeTraits<FClothingSlotState> : public TStructOpsTypeTraitsBase2<FClothingSlotState>
{
    enum
    {
        WithNetSerializer = true
    };
};

template<>
struct TStructOpsTypeTraits<FCharacterCustomizationData> : public TStructOpsTypeTraitsBase2<FCharacterCustomizationData>
{
    enum
    {
        WithNetSerializer = true
    };
};

// ---------------------------------------------------------------------------
// 구현 (헤더 내 인라인)
// ---------------------------------------------------------------------------

inline bool FClothingSlotState::NetSerialize(FArchive& Ar, UPackageMap* Map, bool& bOutSuccess)
{
    // 슬롯 종류
    uint8 SlotId = static_cast<uint8>(Slot);
    Ar.SerializeBits(&SlotId, 8);
    if (Ar.IsLoading())
    {
        Slot = static_cast<EClothingSlot>(SlotId);
    }

    // 아이템 ID: FName 두 개로 나눠 보낸다(FName은 네트워크 아카이브에서 문자열로 직렬화된다).
    FName AssetType = ItemId.PrimaryAssetType.GetName();
    FName AssetName = ItemId.PrimaryAssetName;
    Ar << AssetType;
    Ar << AssetName;
    if (Ar.IsLoading())
    {
        ItemId = FPrimaryAssetId(FPrimaryAssetType(AssetType), AssetName);
    }

    // 가림 여부
    uint8 bHide = bHideBodyUnderneath ? 1 : 0;
    Ar.SerializeBits(&bHide, 1);
    if (Ar.IsLoading())
    {
        bHideBodyUnderneath = (bHide != 0);
    }

    // 색 파라미터: 이름 + 8비트 RGBA. 최대 8개까지만 복제한다.
    uint8 ColorCount = static_cast<uint8>(FMath::Min(Colors.Num(), 8));
    Ar.SerializeBits(&ColorCount, 4);
    if (Ar.IsLoading())
    {
        Colors.SetNum(ColorCount);
    }

    for (uint8 ColorIndex = 0; ColorIndex < ColorCount; ++ColorIndex)
    {
        FClothingColorParameter& Color = Colors[ColorIndex];
        Ar << Color.ParameterName;

        uint8 Channels[4] = { 0, 0, 0, 0 };
        if (Ar.IsSaving())
        {
            Channels[0] = FCharacterCustomizationData::QuantizeUnit(Color.Value.R);
            Channels[1] = FCharacterCustomizationData::QuantizeUnit(Color.Value.G);
            Channels[2] = FCharacterCustomizationData::QuantizeUnit(Color.Value.B);
            Channels[3] = FCharacterCustomizationData::QuantizeUnit(Color.Value.A);
        }

        Ar.SerializeBits(&Channels[0], 8);
        Ar.SerializeBits(&Channels[1], 8);
        Ar.SerializeBits(&Channels[2], 8);
        Ar.SerializeBits(&Channels[3], 8);

        if (Ar.IsLoading())
        {
            Color.Value = FLinearColor(
                FCharacterCustomizationData::DequantizeUnit(Channels[0]),
                FCharacterCustomizationData::DequantizeUnit(Channels[1]),
                FCharacterCustomizationData::DequantizeUnit(Channels[2]),
                FCharacterCustomizationData::DequantizeUnit(Channels[3]));
        }
    }

    bOutSuccess = true;
    return true;
}

inline bool FCharacterCustomizationData::NetSerialize(FArchive& Ar, UPackageMap* Map, bool& bOutSuccess)
{
    // 슬롯 (최대 255)
    uint8 SlotCount = static_cast<uint8>(FMath::Min(Slots.Num(), 255));
    Ar.SerializeBits(&SlotCount, 8);
    if (Ar.IsLoading())
    {
        Slots.SetNum(SlotCount);
    }

    for (uint8 SlotIndex = 0; SlotIndex < SlotCount; ++SlotIndex)
    {
        FClothingSlotState& Entry = Slots[SlotIndex];
        if (Ar.IsLoading())
        {
            Entry = FClothingSlotState();
        }
        Entry.NetSerialize(Ar, Map, bOutSuccess);
    }

    // 모프 타깃: 이름 + 8비트 가중치
    uint8 MorphCount = static_cast<uint8>(FMath::Min(MorphTargets.Num(), 64));
    Ar.SerializeBits(&MorphCount, 6);
    if (Ar.IsLoading())
    {
        MorphTargets.SetNum(MorphCount);
    }

    for (uint8 MorphIndex = 0; MorphIndex < MorphCount; ++MorphIndex)
    {
        FCharacterMorphTarget& Morph = MorphTargets[MorphIndex];
        Ar << Morph.Name;

        uint8 Weight = 0;
        if (Ar.IsSaving())
        {
            Weight = QuantizeUnit(Morph.Weight);
        }
        Ar.SerializeBits(&Weight, 8);
        if (Ar.IsLoading())
        {
            Morph.Weight = DequantizeUnit(Weight);
        }
    }

    // 체형 스케일 3종 (0.85 ~ 1.15)
    uint8 HeightByte = 0;
    uint8 LegByte = 0;
    uint8 ShoulderByte = 0;
    if (Ar.IsSaving())
    {
        HeightByte = QuantizeRange(HeightScale, 0.85f, 1.15f);
        LegByte = QuantizeRange(LegLengthScale, 0.85f, 1.15f);
        ShoulderByte = QuantizeRange(ShoulderWidthScale, 0.85f, 1.15f);
    }
    Ar.SerializeBits(&HeightByte, 8);
    Ar.SerializeBits(&LegByte, 8);
    Ar.SerializeBits(&ShoulderByte, 8);
    if (Ar.IsLoading())
    {
        HeightScale = DequantizeRange(HeightByte, 0.85f, 1.15f);
        LegLengthScale = DequantizeRange(LegByte, 0.85f, 1.15f);
        ShoulderWidthScale = DequantizeRange(ShoulderByte, 0.85f, 1.15f);
    }

    // 피부·헤어
    uint8 SkinChannels[4] = { 0, 0, 0, 0 };
    uint8 HairChannels[4] = { 0, 0, 0, 0 };
    if (Ar.IsSaving())
    {
        SkinChannels[0] = QuantizeUnit(SkinTint.Value.R);
        SkinChannels[1] = QuantizeUnit(SkinTint.Value.G);
        SkinChannels[2] = QuantizeUnit(SkinTint.Value.B);
        SkinChannels[3] = QuantizeUnit(SkinTint.Value.A);
        HairChannels[0] = QuantizeUnit(HairTint.Value.R);
        HairChannels[1] = QuantizeUnit(HairTint.Value.G);
        HairChannels[2] = QuantizeUnit(HairTint.Value.B);
        HairChannels[3] = QuantizeUnit(HairTint.Value.A);
    }

    for (int32 Channel = 0; Channel < 4; ++Channel)
    {
        Ar.SerializeBits(&SkinChannels[Channel], 8);
        Ar.SerializeBits(&HairChannels[Channel], 8);
    }

    if (Ar.IsLoading())
    {
        SkinTint.ParameterName = TEXT("SkinTint");
        SkinTint.Value = FLinearColor(
            DequantizeUnit(SkinChannels[0]), DequantizeUnit(SkinChannels[1]),
            DequantizeUnit(SkinChannels[2]), DequantizeUnit(SkinChannels[3]));
        HairTint.ParameterName = TEXT("HairColor");
        HairTint.Value = FLinearColor(
            DequantizeUnit(HairChannels[0]), DequantizeUnit(HairChannels[1]),
            DequantizeUnit(HairChannels[2]), DequantizeUnit(HairChannels[3]));
    }

    // 주근깨·흉터
    uint8 FreckleByte = 0;
    uint8 ScarByte = 0;
    if (Ar.IsSaving())
    {
        FreckleByte = QuantizeUnit(FreckleAmount);
        ScarByte = QuantizeUnit(ScarAmount);
    }
    Ar.SerializeBits(&FreckleByte, 8);
    Ar.SerializeBits(&ScarByte, 8);
    if (Ar.IsLoading())
    {
        FreckleAmount = DequantizeUnit(FreckleByte);
        ScarAmount = DequantizeUnit(ScarByte);
    }

    // 헤어 스타일 ID
    Ar << HairStyleId;

    bOutSuccess = true;
    return true;
}
