// Copyright (c) 2026. Example code for the open world architecture guide (in-game building).
//
// BuildingTypes.h
//   인게임 건축(런타임 건설) 시스템의 데이터 계약.
//   - 조각 정의(UBuildPieceDefinition): 메시·크기·소켓·지지 비용
//   - 배치 결과(EPlacementResult): 클라이언트 프리뷰와 서버 검증이 같은 열거형을 쓴다
//   - 저장 레코드(FBuildPieceRecord): 세이브/리플레이용 직렬화(NetSerialize 포함)

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "UObject/PrimaryAssetId.h"
#include "BuildingTypes.generated.h"

class UStaticMesh;

/** 건축 조각의 종류. 슬롯 UI와 지지 규칙이 이 값으로 갈린다. */
UENUM(BlueprintType)
enum class EBuildPieceType : uint8
{
    Foundation  UMETA(DisplayName = "Foundation"),
    Floor       UMETA(DisplayName = "Floor"),
    Wall        UMETA(DisplayName = "Wall"),
    Pillar      UMETA(DisplayName = "Pillar"),
    Stair       UMETA(DisplayName = "Stair"),
    Roof        UMETA(DisplayName = "Roof"),

    Count       UMETA(Hidden)
};

/** 배치 판정 결과. 실패 사유를 UI 문구로 매핑한다. */
UENUM(BlueprintType)
enum class EPlacementResult : uint8
{
    Valid           UMETA(DisplayName = "Valid"),
    NoHit           UMETA(DisplayName = "No Hit"),
    OutOfRange      UMETA(DisplayName = "Out Of Range"),
    Overlapping     UMETA(DisplayName = "Overlapping"),
    NoSupport       UMETA(DisplayName = "No Support"),
    TooSteep        UMETA(DisplayName = "Too Steep"),
    InvalidDefinition UMETA(DisplayName = "Invalid Definition")
};

/** 조각 하나의 정의. AssetManager가 스캔한다. */
UCLASS(BlueprintType)
class MYGAME_API UBuildPieceDefinition : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build")
    EBuildPieceType PieceType = EBuildPieceType::Wall;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build")
    TSoftObjectPtr<UStaticMesh> Mesh;

    /** 충돌·스냅 계산에 쓰는 절반 크기(cm). 예: 4 m 벽 → (200, 10, 150) */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build")
    FVector ExtentCm = FVector(200.f, 10.f, 150.f);

    /** 조각 메시의 소켓 이름 목록. 예: Snap_Top / Snap_Bottom / Snap_Left */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build")
    TArray<FName> SnapSockets;

    /** 지지 하중 계산에서 이 조각이 차지하는 무게. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build", meta = (ClampMin = "1"))
    int32 SupportCost = 1;

    /** 지지(기초·기둥·바닥)가 필요한가. 기초는 false. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build")
    bool bRequiresSupport = true;

    /** 바닥/기초 위에 놓이면 하중의 뿌리가 되는가. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build")
    bool bIsRoot = false;

    /** 뿌리 조각이 견딜 수 있는 누적 지지 비용. 넘으면 붕괴한다. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build", meta = (ClampMin = "1"))
    int32 SupportCapacity = 8;

    /** 이 조각에서 다른 조각으로 지지가 전파되는 최대 거리(cm). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Build", meta = (ClampMin = "10"))
    float MaxSupportGapCm = 25.f;

    virtual FPrimaryAssetId GetPrimaryAssetId() const override
    {
        return FPrimaryAssetId(TEXT("BuildPiece"), GetFName());
    }
};

/** 저장·리플레이용 조각 레코드. 액터 포인터 대신 안정 ID를 쓴다. */
USTRUCT(BlueprintType)
struct FBuildPieceRecord
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Build")
    FGuid PieceId;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Build")
    FPrimaryAssetId DefinitionId;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Build")
    FVector Location = FVector::ZeroVector;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Build")
    FQuat Rotation = FQuat::Identity;

    /** 이 조각을 지지하는 조각(스냅 부모). 뿌리면 무효 GUID. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Build")
    FGuid SupportPieceId;

    bool NetSerialize(FArchive& Ar, class UPackageMap* Map, bool& bOutSuccess);
};

template<>
struct TStructOpsTypeTraits<FBuildPieceRecord> : public TStructOpsTypeTraitsBase2<FBuildPieceRecord>
{
    enum
    {
        WithNetSerializer = true
    };
};

inline bool FBuildPieceRecord::NetSerialize(FArchive& Ar, UPackageMap* Map, bool& bOutSuccess)
{
    Ar << PieceId;
    Ar << DefinitionId;
    Ar << Location;
    Ar << Rotation;
    Ar << SupportPieceId;

    bOutSuccess = true;
    return true;
}

/** 스냅 계산 도우미. 클라이언트 프리뷰와 서버 검증이 같은 함수를 쓴다. */
namespace BuildSnap
{
    /** 표준 건축 그리드(cm). 100 cm = 1 uu * 100 */
    constexpr float GridCm = 100.f;

    inline FVector SnapToGrid(const FVector& InLocation, float InGrid = GridCm)
    {
        return FMath::GridSnap(InLocation, InGrid);
    }

    /** 요(yaw)만 90도 단위로 스냅한다. 벽·바닥은 수평을 유지한다. */
    inline FQuat SnapYawToQuarterTurns(const FQuat& InRotation, float InStepDegrees = 90.f)
    {
        const FRotator Rotator = InRotation.Rotator();
        const float SnappedYaw = FMath::GridSnap(Rotator.Yaw, InStepDegrees);
        return FRotator(0.f, SnappedYaw, 0.f).Quaternion();
    }
}
