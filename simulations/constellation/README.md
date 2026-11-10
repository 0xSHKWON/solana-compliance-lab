# Constellation Simulator

제안된 Constellation 프로토콜의 거래 포함 규칙을 버전별 모델로 시뮬레이션하고, 기존 단일 리더 모델과 비교합니다. (포트 8004)
`POST /internal/v1/constellation/simulate`: ConstellationSimulationRequest → ConstellationSimulationResult

## 처리 순서

1. 구조 검증: attestationPercent 0~100, 음수·타입 오류 → 400
2. `protocolModelVersion`이 등록되지 않은 버전이면 → 422 `UNSUPPORTED_VERSION`
3. 정의상 모순된 시나리오 → `INVALID_SCENARIO` (`REJECTING_COUNT_EXCEEDS_TOTAL`, `CONTRADICTORY_SUBMISSION_PATH`)
4. 선택한 모델로 판정. 같은 시나리오는 같은 결과(`simulationId` 포함)를 냅니다.

## 모델

### `0.1.0-draft` — Constellation 규칙 초안

| 단계 | 조건 | 결과 |
| --- | --- | --- |
| 제안자 경로 | 수락 제안자 0명 | `NO_SUBMISSION_PATH` / `NO_ACCEPTING_PROPOSER` |
| | 수락 제안자에게 미제출 | `NO_SUBMISSION_PATH` / `NOT_SUBMITTED_TO_ACCEPTING_PROPOSER` |
| pslice 가용성 | pslice 불가 | 포함 강제 안 됨 / `PSLICE_UNAVAILABLE` |
| 증명 조건 | attestationPercent ≥ 임계값(기본 66.67) | 포함 강제 / `ATTESTATION_CONDITION_MET` |
| | 미만 | 포함 강제 안 됨 / `ATTESTATION_CONDITION_NOT_MET` |
| 리더 제외 | 시도 없음 | `leaderExclusionValid: null` / `NO_EXCLUSION_ATTEMPT` |
| | 포함 강제된 pslice 제외 시도 | `false` / `LEADER_EXCLUSION_INVALID` |
| | 강제되지 않은 pslice 제외 시도 | `true` / `LEADER_EXCLUSION_VALID` |

결과: 포함 강제 → `INCLUSION_ENFORCED`, 아니면 `INCLUSION_NOT_ENFORCED`. 제출 경로가 없으면 제외할 대상이 없으므로 `leaderExclusionValid: null`입니다.

### `0.1.0-single-leader` — 비교 기준

리더 한 명이 블록 구성을 결정하고 pslice·증명에 의한 포함 강제 장치가 없습니다.

- 제출 경로 판정은 초안 모델과 같습니다.
- 경로가 있으면 항상 `INCLUSION_NOT_ENFORCED`이고, 리더의 제외 시도는 항상 유효(`LEADER_EXCLUSION_VALID`)입니다.

예: 4명 중 1명 거절, 수락 제안자에게 제출, pslice 가용, 증명 100%, 리더 제외 시도인 경우
- `0.1.0-draft` → `INCLUSION_ENFORCED`, 제외 무효
- `0.1.0-single-leader` → `INCLUSION_NOT_ENFORCED`, 제외 유효

## 주의

- 초안 규칙과 임계값은 팀 초안이며 리서치팀 공식 확정 전입니다. 확정되면 설정값을 바꾸거나 새 `ProtocolModel` 버전을 Bean으로 추가합니다.
- `CONSTELLATION_MOCK_ENABLED=true`이면 mock 버전(`0.0.0-research-pending`)에 화면 확인용 고정 결과를 반환합니다(`MOCK_RESULT_NOT_PROTOCOL_VALIDATED`).
- 포함 확률이나 제재 우회 성공률은 계산하지 않습니다(`simulationOnly: true`).

```bash
./mvnw -pl simulations/constellation spring-boot:run
./mvnw -pl simulations/constellation test
```
