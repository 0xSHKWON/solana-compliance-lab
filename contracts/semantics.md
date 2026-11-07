# 공통 계약 의미

이 문서는 구조 검증으로 표현하기 어려운 의미를 정의합니다. 위험 규칙의 수치와 미정 API 세부 사항은 구현 가능한 데모를 위한 제안이며 법률상 제재 기준이 아닙니다.

## Collector / Normalizer

- scope는 `[fromTime, toTime)`이며 fromTime < toTime입니다. maxTransactions는 조회할 고유 거래의 상한입니다. 하나의 거래에 여러 전송이 있을 수 있습니다.
- normalized transfer의 id는 입력 순서와 무관하게 안정적이어야 합니다. signature + instructionIndex + innerInstructionIndex + transferOrdinal 조합이 중복되면 안 됩니다. 같은 서명의 복수 명령어를 하나의 전송으로 합치지 않습니다.
- instructionIndex와 transferOrdinal은 0부터 시작합니다. innerInstructionIndex: null은 최상위 명령어입니다. 내부 명령어는 부모 최상위 instructionIndex와 내부 인덱스를 함께 기록합니다.
- fromAddress/toAddress는 소유자 지갑입니다. sourceAccount/destinationAccount는 실제 전송 계정입니다. SOL은 각각 같은 주소입니다. SPL/TOKEN_2022는 토큰 계정과 소유자를 구분합니다.
- ownerResolved는 양쪽 소유자가 모두 확인되었을 때만 true입니다. 한쪽이라도 null이면 false이며 coverage에 OWNER_UNRESOLVED를 기록합니다. 미확인 소유자를 토큰 계정 주소로 채우지 않습니다.
- timestamp: null은 TIMESTAMP_UNAVAILABLE 사유로 기록합니다. 다른 전송의 시각이나 수집 시각으로 추정하지 않습니다. 같은 signature의 slot·timestamp는 일치해야 합니다.
- 정상 성공한 전송만 배열에 넣습니다. 실패 거래, 미지원 명령어, 파싱 실패를 정상적인 빈 조회로 바꾸지 않습니다. 필요한 경우 PARSE_FAILED·UNSUPPORTED_INSTRUCTION 등으로 PARTIAL을 기록합니다.
- transferCount는 배열 길이와 같습니다. transactionCount는 중복 제거한 조회 거래 수이며 전송을 추출하지 못한 거래를 포함할 수 있습니다. 따라서 고유 signature 수보다 작을 수 없고 요청 maxTransactions를 넘으면 안 됩니다. 후자는 원래 요청과 연결하여 검사합니다.
- snapshotSlot이 있으면 모든 전송 slot보다 크거나 같아야 합니다. 스냅샷 기준 슬롯이며 실제 확정성 보증은 데이터 공급자 조건을 따릅니다.
- COMPLETE는 빈 reasons와 reachedTimeBoundary: true를 요구합니다. PARTIAL은 하나 이상의 사유가 필요합니다. 상한에 도달해서 범위를 확인하지 못하면 TRANSACTION_LIMIT_REACHED와 reachedTimeBoundary: false입니다.
- 빈 transfers, transactionCount: 0, COMPLETE는 정상적인 빈 조회입니다. 제공자 실패로 Snapshot 자체를 만들 수 없으면 구조화된 오류를 반환합니다.
- 레이블 조회 실패 시 마지막으로 확보한 데이터셋의 실제 버전·fetchedAt을 기록하고 LABEL_DATASET_UNAVAILABLE로 PARTIAL 처리할 수 있습니다. 유효한 데이터셋 메타데이터 자체가 없으면 시각·버전을 꾸며내지 말고 수집 오류를 반환합니다.
- labels는 labelDataset과 source·network가 같아야 합니다. 동일 원본 제재 항목의 referenceId가 여러 주소에 연결될 수 있으므로 address + source + referenceId를 중복 키로 사용합니다.
- dataProvenance는 **거래 데이터**의 출처입니다. ON_CHAIN/SYNTHETIC과 레이블의 OFAC_SDN/TEST_FIXTURE를 별개로 표시합니다. 실제 거래에 테스트 레이블을 적용한 실험을 실제 제재 사례로 표시하지 않습니다.
- LIVE는 ON_CHAIN만 허용합니다. FIXTURE는 ON_CHAIN/SYNTHETIC 모두 허용합니다. API 키가 포함된 RPC URL을 reference로 기록하지 않습니다.

## KYT

외부 RPC·DB 호출 없이 Snapshot만 분석합니다. 입력 객체를 수정하지 않습니다. 모든 주소·원시 수량·근거 참조를 보존합니다.

| 규칙 | 정의 |
| --- | --- |
| SANCTION_EXACT | 분석 address가 SANCTIONED 레이블과 직접 일치 |
| SANCTION_DIRECT_FLOW | 분석 지갑이 참여한 양수 전송의 반대편 소유자 또는 반대편 전송 계정이 SANCTIONED 레이블과 일치 |
| RAPID_FAN_OUT | 분석 지갑이 송신한 양수 전송이 시간창 안에서 서로 다른 수신자 수에 도달 |
| RAPID_REPEAT | 분석 지갑이 같은 수신자·자산에 보낸 양수 전송의 서로 다른 거래 서명 수가 시간창 안에서 기준에 도달 |

제재 주소와 자체 주소의 일치, 제재 상대방과의 거래는 다른 규칙입니다. INCIDENT/OTHER 레이블을 제재 목록으로 간주하지 않습니다. 간접 연결이나 다중 홉 추적은 이 버전의 탐지 범위가 아닙니다.

시간창은 양 끝을 포함하여 시간차 <= windowSeconds입니다. 동일 시각 정렬은 signature·명령어 위치·id로 안정화합니다. 미확인 timestamp는 시간 규칙에서 제외하며 전체 분석은 PARTIAL로 남깁니다. 소유자 미확인 거래의 계정 주소를 수신 지갑으로 간주하여 패턴을 확정하지 않습니다. 직접 거래 규칙은 확인된 반대편 계정과 제재 레이블의 정확한 일치를 근거로 남길 수 있습니다.

Fan-out은 자산별 수량 합산 없이 고유 수신자를 셉니다. Repeat는 recipient + asset.type + mint별로 그룹화하며 동일 서명의 여러 명령어를 여러 거래로 세지 않습니다. 수신자 지갑을 확인할 수 없는 전송과 자기 지갑으로의 전송은 시간 패턴의 근거로 사용하지 않습니다.

예시 Ruleset 1.0.0은 EXACT 100, DIRECT_FLOW 80, FAN_OUT 35, REPEAT 25점을 사용합니다. 같은 규칙은 여러 번 탐지되어도 점수에 한 번만 기여합니다. 총점은 min(100, 고유 탐지 규칙 기여도 합)입니다. 완전한 데이터에서 0점·탐지 없음은 LOW, 양수·70점 미만은 MEDIUM, 70점 이상은 HIGH입니다. 각 detectedRule의 riskLevel은 개별 신호의 수준입니다.

coverage.status가 PARTIAL이면 종합 riskScore와 riskLevel은 모두 null입니다. 이미 발견한 detectedRules와 evidences는 보존합니다. null을 탐지 없음으로 해석하지 않습니다. LOW도 적법성·안전성을 보장하지 않습니다.

각 detectedRule은 ruleId·ruleVersion·scoreContribution·evidenceIds를 제공합니다. Evidence는 원본 signature, transfer id, 관련 주소, 레이블 원본 referenceId, Snapshot·레이블 데이터셋 출처를 기록합니다. 주소 자체 일치는 거래 없이도 탐지 가능하므로 해당 근거의 transferIds와 transactionSignatures가 비어 있을 수 있습니다. 근거 ID는 유일하고 탐지 규칙에서 참조되어야 하며, 참조한 전송·레이블은 Snapshot에 존재해야 합니다.

직접 일치의 근거는 ADDRESS_LABEL과 레이블 참조를, 직접 거래의 근거는 DIRECT_FLOW와 전송·서명·레이블 참조를 요구합니다. 시간 패턴은 TEMPORAL_PATTERN과 복수 전송을, 반복 거래는 서로 다른 복수 서명을 요구합니다. 모든 근거의 relatedAddresses에는 분석 대상이 포함되어야 합니다.

## Policy

TransactionIntent와 송신자·수신자 평가를 검증하고 결정을 반환합니다. 실제 거래 제출이나 차단은 수행하지 않습니다. KYT를 다시 실행하거나 외부 주소 정보를 조회하지 않습니다.

- assessments의 subjectAddress는 각각 intent.sender/recipient와 일치해야 합니다. 같은 주소이면 동일한 평가를 사용합니다. 서로 다른 주소의 평가를 재사용하면 오류입니다.
- 필수 평가 객체 누락·형식 오류는 400입니다. 유효한 평가이지만 riskScore/riskLevel이 null인 것은 불충분한 분석으로 REVIEW 후보입니다.
- 정책이 지원하지 않는 rulesetVersion 또는 policyVersion은 422 UNSUPPORTED_VERSION입니다. 알 수 없는 버전을 최신 버전으로 대체하지 않습니다.
- SANCTION_EXACT는 BLOCK입니다. SANCTION_DIRECT_FLOW는 정책 1.0.0에서 REVIEW, 1.1.0에서 BLOCK입니다. 부분 수집이라도 확인된 직접 일치 근거는 보존하여 이 정책을 적용합니다.
- 기타 위험 신호는 warningAction, 전체 HIGH는 highRiskAction을 적용합니다. 설정값은 버전 파일로 고정합니다.
- 최종 우선순위는 BLOCK > REVIEW > WARN > ALLOW입니다. 양쪽 모두 완전하고 위험 신호가 없을 때만 ALLOW입니다. 판단에 기여한 사유는 reasonCodes에 보존합니다.
- 종합 riskScore는 양쪽이 모두 알려진 경우 최댓값, 하나라도 null이면 null입니다. riskLevel도 동일하게 null을 전파하며 알려진 경우 더 높은 등급을 사용합니다. 합산하여 동일 근거를 이중 계산하지 않습니다.
- referencedEvidenceIds는 입력 평가에 실제 존재해야 합니다. 동일 evidenceId가 서로 다른 내용으로 중복되면 거부합니다.
- 이 요청에는 평가 시각 필드가 없으므로 Policy가 평가의 신선도를 추정하지 않습니다. Backend가 저장 시각·분석 상태·조회 범위·버전을 확인하여 유효한 평가를 선택합니다.
- 재현 가능한 평가 기준 시각으로 intent.requestedAt을 사용하여 evaluatedAt에 기록합니다. 실제 서버 처리 시각은 Backend 감사 로그로 별도 관리합니다.
- 동일 의미의 입력과 버전에서는 순서와 실행 시각에 관계없이 같은 결과를 반환합니다. 엔진의 ID는 정규화한 의미 데이터의 SHA-256으로 생성하며 requestId는 판단 결과를 바꾸지 않습니다.

## Backend / Frontend

분석 상태 전이는 QUEUED → RUNNING → COMPLETED/PARTIAL/FAILED 및 QUEUED → FAILED입니다. 종료 상태의 재시도는 새 analysisId로 추적합니다. 폴링에서 중간 상태를 건너뛰어 관측할 수 있습니다.

QUEUED/RUNNING은 결과 필드가 null입니다. COMPLETED는 COMPLETE coverage와 숫자 점수, PARTIAL은 PARTIAL coverage와 null 종합 점수 및 확보한 근거를 제공합니다. FAILED는 error를 제공하며 정상적인 빈 결과로 표시하지 않습니다. 실패 전 저장된 Snapshot은 Backend 내부에 보존할 수 있으나 이 조회 응답에서는 최종 결과로 노출하지 않습니다.

분석 조회는 작업이 존재하면 FAILED도 HTTP 200입니다. 없는 ID는 404입니다. 거래 페이지는 완료·부분 완료된 Snapshot의 안정적인 순서와 불투명 cursor를 사용합니다. 기본 limit 100, 최대 1000이며 마지막 페이지 nextCursor는 null입니다. 아직 Snapshot이 공개되지 않았으면 409 ANALYSIS_NOT_READY입니다.

Public 정책 요청은 양쪽 분석 ID와 intent를 참조합니다. Backend는 주소·네트워크·작업 상태·버전을 검증한 뒤 저장된 평가로 Internal 요청을 만듭니다. PARTIAL 결과도 유효한 불완전 평가이므로 Policy에 넘겨 REVIEW/BLOCK 근거를 받을 수 있습니다. QUEUED/RUNNING/FAILED는 409 ANALYSIS_NOT_READY, 주소 불일치는 409 ASSESSMENT_MISMATCH입니다.

Public 정책 응답의 intent·assessments·decision은 그대로 표시·보관합니다. Gateway 요청의 intentId와 decisionId는 저장된 동일 심사 기록에 속해야 합니다. 브라우저의 위험 점수나 정책 Action 입력을 신뢰하지 않습니다.

## Gateway

| policyEnforced | action | warningAcknowledged | outcome | reasonCodes |
| --- | --- | --- | --- | --- |
| false | 모든 값 | 모든 값 | SUBMISSION_ALLOWED | POLICY_NOT_ENFORCED |
| true | ALLOW | 모든 값 | SUBMISSION_ALLOWED | POLICY_ALLOW |
| true | BLOCK | 모든 값 | SUBMISSION_REJECTED | POLICY_BLOCK |
| true | REVIEW | 모든 값 | REVIEW_REQUIRED | POLICY_REVIEW |
| true | WARN | false | REVIEW_REQUIRED | WARNING_NOT_ACKNOWLEDGED |
| true | WARN | true | SUBMISSION_ALLOWED | WARNING_ACKNOWLEDGED |

intentId·decision.intentId는 일치해야 합니다. 실제 전송이 아니므로 actualBroadcast는 항상 false입니다. 허용은 제출 경로의 모의 허용이며 실제 네트워크 포함을 뜻하지 않습니다. 정책 미적용은 다른 서비스/RPC의 실제 정책을 관측했다는 뜻이 아닙니다.

## Constellation

요청·응답 형태만 고정합니다. 현재 승인된 protocolModelVersion은 없습니다. 실제 구현에서는 미등록 모델에 422 UNSUPPORTED_VERSION을 반환하며 mockVersion으로 실제 판정을 실행하지 않습니다.

리서치 승인 전에 attestationPercent 임계값, pslice 가용성·증명 조건과 포함 강제의 관계, 리더 제외의 유효성, 단일 리더 비교 규칙을 코드로 임의 확정하지 않습니다. 승인 시 출처·파라미터·버전·검증 시나리오를 함께 등록합니다.

attestationPercent는 0~100 범위입니다. 음수·잘못된 타입 등 구조 오류는 400입니다. 거절 제안자 수가 전체보다 큰 등 구조상 유효하나 모순된 조건은 INVALID_SCENARIO 결과로 표현합니다. 해당 결과에서는 경로·포함 강제 false, leaderExclusionValid: null입니다. 제외 시도 자체가 없으면 leaderExclusionValid: null입니다. simulationOnly는 항상 true입니다.

현재 mock Fixture는 시각화 계약용입니다. 포함 확률·제재 우회 성공률·메인넷 거래 성공을 계산하거나 보장하지 않습니다.

## 오류

모든 실패는 HTTP 상태와 `{error: {code, message, retryable}, requestId}`를 제공합니다.

| HTTP | code 예시 |
| --- | --- |
| 400 | CONTRACT_VALIDATION_FAILED, INVALID_REQUEST |
| 404 | NOT_FOUND |
| 409 | CONFLICT, ANALYSIS_NOT_READY, ASSESSMENT_MISMATCH |
| 413 / 415 | INVALID_REQUEST: 과도한 본문 / 비지원 Content-Type |
| 422 | UNSUPPORTED_VERSION: 스키마·규칙·정책·프로토콜 버전 미지원 |
| 429 | RATE_LIMITED |
| 500 | INTERNAL_ERROR |
| 502 / 503 | UPSTREAM_UNAVAILABLE |

지원하지 않는 schemaVersion은 다른 스키마 오류보다 먼저 검사합니다. retryable은 실제 원인에 따라 정하며 내부 예외·API 키는 오류 메시지에 노출하지 않습니다.
