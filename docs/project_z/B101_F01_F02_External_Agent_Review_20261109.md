# 늘봄1단지 101동 F01–F02 외부 에이전트 검토용 인계서

> 작성일: 2026-11-09  
> 목적: 다른 에이전트가 현재 맵을 직접 수정하기 전에 F01–F02의 설계 계약, 구현 범위, 실패 이력, 미승인 사항을 같은 기준으로 검토하도록 하는 독립 문서다.  
> 판정 원칙: 수치 검사나 Automation 통과는 육안·PIE 승인을 대신하지 않는다.

## 1. 실행 가드

- 유일한 대상 프로젝트: `D:/5.8project/Project_Z/Project_Z.uproject`
- 엔진: Unreal Engine `5.8.x`
- 대상 맵: `/Game/Project_Z/Maps/Prototype/L_Neulbom1_B101_ModulePrototype_v02`
- `D:/5.7project/Z_Department`는 과거 이관 원본이다. 실행·빌드·저장·Commandlet·Automation을 금지한다.
- 이 문서는 검토용 요약이다. 실제 변경 전에는 `IntegrationMigration/PROJECT_EXECUTION_GUARD.md`와 분야별 Current 문서를 읽는다.

## 2. 층 표기와 현재 범위

- `F01`: 지상 1층이며 공동현관이 있는 층이다.
- `F02`: 지상 2층이며 첫 반복층 후보지만 아직 Typical Floor로 승인되지 않았다.
- 층고 기준: `320cm`.
- 현재 검토 범위는 F01과 F02뿐이다. F03 이상과 15층 적층은 F01/F02 육안·PIE 승인 전 생성 금지다.

## 3. 건축 기준

| 항목 | 현행 계약 |
|---|---|
| 전체 기준층 외곽 | 2700×1400cm |
| 세대 A | 950×1400cm |
| 공용 Core | 800×1400cm |
| 세대 B | 950×1400cm, A와 동일형·동일면적 |
| 세대 구성 | 침실 2, 욕실 2, Open LDK, 현관 전실·수납 완충, 드레스룸, 다용도실, 대피공간 |
| 주동선 | `CoreLobby -> Foyer -> EntryStorageBuffer -> OpenLivingDining` |
| 금지 동선 | 현관에서 욕실이나 주방을 통과해 거실로 진입하는 구조 |
| 배치 스냅 | 기본 5cm Grid. 사용자가 확정한 비정규 피벗 보정값은 근거 없이 재정렬하지 않음 |

세대 A와 B는 단순 Mirror 생성물이 아니다. 최종 배치는 각각의 실맵 좌표를 독립적으로 검증해야 한다.

## 4. 현재 구현 범위

| 분야 | 현재 상태 | 남은 승인 |
|---|---|---|
| F01/F02 바닥·외벽·내벽 | 배치 및 수치 감사 수행 | Lit/Wireframe, Capsule 통행, Seam 재검수 |
| 공용 Core | F01/F02 배치 | 로비 동선·계단·승강기 관계 육안 승인 |
| 비상계단 | F01 원본을 기준으로 F02에 Z +320cm 생성, 수치 오차 0 | Headroom·난간·방화문·Capsule 검수 |
| 승강로 | OP180 계열 수직 개구 유지 | 실제 승강기 운행·문 센서·층 호출은 별도 |
| 천장 | 층별 배치, 계단·승강로 개구 보존 | Slab과 2cm 이격의 시각적 품질 확인 |
| 설비 Riser | 층별 배치 | 실제 배관·전기 연결은 후속 |
| 조명·스위치 | 기능형 배치 | 사용자 위치 승인 및 PIE 상호작용 |
| 일반·현관·방화문 | 기능형 회전문 34개, 상부 Header 34개 | 스윙, 문틀, 손잡이, 장애물, 위치 육안 승인 |
| 공동현관문 | F01 4패널 자동문 | 센서, 지연 닫힘, 정전·잠금 PIE |
| 창문 | 기능형 창 17개와 고정 Pane | 재질, Seam, 개폐·Vault·파괴 연동 |
| 세대 현관 중문 | v53 전용 2패널 슬라이딩 중문 4개 | 위치·방향·통과폭 사용자 재승인 필요 |

## 5. 문 구현 상세

### 5.1 회전문

- 총 34개다.
- F01/F02의 세대 A/B마다 현관, 침실2, 공용욕실, 안방, 대피공간, 다용도실, 안방욕실, 드레스룸 문을 각 8개 배치했다.
- 계단실 방화문은 층별 1개다.
- `AProjectZDoorActor` 기반으로 상호작용, 복제, 저장, 잠금, 닫힘 방해물 검사 계약을 유지한다.
- 최근 배치에서는 세대 현관문 4개가 150cm 개구에 맞춰 약 146cm 문짝으로 정규화됐다.

### 5.2 세대 현관 중문 실패와 교체

- v52는 공동현관용 `AProjectZAutomaticSlidingDoorActor`를 실내 중문에 재사용했다.
- 메시 피벗과 보정 범위가 맞지 않아 Actor Bounds가 건물 전체를 가로지르는 수준으로 커졌다. v52 Door Actor는 폐기했고 Jamb/Header만 유지했다.
- v53에서 `AProjectZInteriorSlidingDoorActor`를 신설했다.
- 좌우 2패널, 폭·높이 자동 스케일, 로컬 Bounds 기반 피벗 상쇄, E 개폐, 서버 권한, 복제, Save/Load를 포함한다.
- F01/F02 Unit A/B에 4개를 배치했고 각 Bounds Extent는 `50×80×110cm`다.
- `ProjectZ.Player.Interaction.InteriorSlidingDoor` Automation은 Closed→Open→Closed, 좌우 패널 이동, 저장 상태를 통과했다.
- 그러나 사용자가 실제 위치가 여전히 부자연스럽다고 판정했다. 따라서 현재 상태는 **수치·Automation 통과 / 육안·PIE 미승인**이다.

## 6. 검토가 필요한 설계 충돌

1. 세대 현관 설계 계약은 유효폭 105cm였으나 최근 구현은 150cm 개구와 약 146cm 문짝이다. 어느 치수를 최종 제품 기준으로 삼을지 결정해야 한다.
2. 실내 중문은 100cm 개구의 2패널 중앙개폐 방식이다. 실제 유효 통과폭, 패널 겹침, 벽체 수납 여부가 현실적인지 검토가 필요하다.
3. Unit A의 실맵 Gap은 150cm이고 중문 계약은 100cm라 좌우 25cm Jamb를 사용한다. Unit B Gap은 100cm다. 동일형·동일면적 세대에서 이 차이를 유지할 근거가 있는지 확인해야 한다.
4. 방화문·현관문·욕실문을 포함한 스윙 방향이 대피 동선, 가구, 캡슐 통행과 충돌하지 않는지 확인해야 한다.
5. F02는 F01을 기준으로 생성됐지만 Typical Floor 승격 전이다. F01 고유 요소인 공동현관과 F02 반복 요소를 명확히 분리해야 한다.
6. 계단 위치는 사용자가 실맵에서 조정한 최종 좌표가 권위값이다. 과거 북측 개구 계약이나 대칭 추정값으로 되돌리면 안 된다.
7. 하나의 렌더링 면에는 소유 모듈을 하나만 둔다. Slab·Ceiling·Wall·Opening Edge가 같은 면을 중복 소유하면 Z-Fight가 발생한다.

## 7. 다음 배치부터 사용할 Door Anchor 계약

반복 MCP 배치 대신 사용자가 원하는 위치에 임시 Cube를 놓고 이름만 전달하는 방식이 권장된다.

- 예시 Label: `ANCHOR_B101_F01_UnitA_FoyerInner_OP100x220`
- Origin: 개구 하단 중앙.
- Cube 크기: 실제 개구 폭×벽 두께×높이.
- 로컬 긴 축: 문 폭, 얇은 축: 벽 두께, Z: 높이.
- 사용자는 Anchor Actor 이름만 전달한다.
- 백그라운드 Commandlet가 Transform과 Bounds를 읽어 기능형 문으로 치환하고 JSON 보고서를 생성한다.
- 생성기는 사용자 Anchor 좌표를 대칭 추정, 과거 문서 좌표, 자동 Grid 보정으로 덮어쓰지 않는다.

## 8. 다른 에이전트에게 요청하는 검토 결과 형식

다음 항목을 `통과 / 수정 필요 / 정보 부족`으로 나누어 답변해 주기 바란다.

1. F01/F02 건축 동선과 세대 구성의 현실성.
2. 세대 현관 105cm 계약과 150cm 구현 중 권장안 및 근거.
3. 실내 중문 100cm 2패널 방식의 적합성.
4. Core·비상계단·승강로의 배치 위험.
5. 일반문·방화문의 권장 스윙 방향.
6. F02를 Typical Floor로 승격하기 전에 반드시 고칠 사항.
7. 수정 좌표를 제안할 경우 `Actor/Anchor 이름, Location XYZ, Rotation PYR, 개구 폭·높이, 벽 두께`를 수치로 제시한다.

## 9. 근거 자료

- 최신 인계: `IntegrationMigration/아파트_101동_압축후_재개_인계_20261028.md`
- 세대 평면: `ByExtension/md/B101_세대A_상세평면_재설계_20261029.md`
- Core 좌표 계약: `ByExtension/md/B101_Core_공간좌표_고정계약_20261029.md`
- 승강로 계획: `ByExtension/md/B101_승강기_승강로_설계수정계획_20261103.md`
- v52 결과: `IntegrationMigration/Neulbom1B101Prototype/B101_DoorFitout_v52.json`
- v53 결과: `IntegrationMigration/Neulbom1B101Prototype/B101_InteriorSlidingDoor_v53.json`
- v53 배치 스크립트: `IntegrationMigration/Neulbom1B101Prototype/ue58_replace_b101_foyer_sliding_doors_v53.py`

## 10. 현재 결론

F01과 F02는 구조·Core·계단·승강로·문·창문·천장·조명·스위치·Riser가 배치된 **검토 가능한 프로토타입**이다. 아직 완성층이나 반복 생성 원본은 아니다. 특히 세대 현관문 치수와 실내 중문 위치는 외부 검토 및 사용자 육안 승인을 받은 뒤 확정해야 한다.
