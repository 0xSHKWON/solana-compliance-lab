# 계약 의미와 런타임 검증

이 문서의 수치·우선순위·경로는 Draft v2.1을 실행 가능한 계약으로 구체화한 **초안 제안**입니다. 팀 합의 전 확정된 정책으로 취급하지 않습니다.

## 공통 런타임 검사

JSON Schema로 구조를 검사한 후 아래 의미도 모듈 경계에서 검사합니다.

- 주소는 Base58 디코딩 후 32바이트, 서명은 64바이트여야 합니다. 정규식 검사는 길이와 문자만 확인합니다.
- 시간 구간은 `from < to`여야 합니다. `observedRange`만 단일 시점인 `from == to`를 허용합니다.
- snapshot/evaluation/decision/transferRequest 식별자는 연결된 원본과 일치해야 합니다. 내용이 바뀌면 새 ID를 사용합니다.
- 목록 안의 transferId, labelId, ruleId, findingId, routeId, proposerId는 각각 중복되면 안 됩니다.
- 평가의 snapshotId·walletAddress·coverageStatus는 입력 Snapshot과 일치해야 합니다.
- EvidenceRef의 transferIds·labelIds는 해당 snapshotId에 실제 존재해야 합니다. 근거가 지갑 레이블만인 경우 transferIds는 비어 있을 수 있습니다.
- 비활성 또는 미평가 규칙은 finding을 생성하지 않습니다. 규칙 ID는 입력 RuleSet에 존재해야 합니다.
- UTC 시각·규칙·정책·데이터의 의미가 같으면 점수·등급·탐지·결정도 같아야 합니다. 실행 ID와 실행 시각 자체의 일치는 요구하지 않습니다. Policy의 `asOf`도 재현 가능한 입력입니다.

## Collector / Normalizer

- 조회 범위는 `[from, to)`이며 COMPLETE는 요청한 범위와 지원하는 전송 유형에 대한 완전성입니다. 전체 체인의 모든 경제 활동을 수집했다는 뜻이 아닙니다.
- maxTransactions는 RPC 서명/거래 조회 상한이며 전송 수 상한이 아닙니다. 한 거래에서 여러 Transfer가 나올 수 있습니다.
- fetchedTransactionCount는 중복 제거한 조회 거래 수, normalizedTransactionCount는 지원 여부를 판단하고 정규화를 완료한 거래 수입니다. 두 값은 전송 배열 길이와 다를 수 있습니다. 후자는 전자보다 클 수 없으며 전자는 상한을 넘지 않습니다.
- Transfer는 성공한 SOL/SPL 자금 이동만 표현합니다. 실패 거래·수수료·지원하지 않는 호출을 임의의 송금으로 변환하지 않습니다. 상세 지원 범위는 Collector 구현과 함께 명시합니다.
- 동일 거래 안의 복수 전송은 transferId로 구분합니다. signature가 같다는 이유로 복수 전송을 제거하지 않습니다. transferId 생성 규칙은 Normalizer 버전에 고정합니다.
- blockTime을 얻지 못하면 null로 두고 MISSING_BLOCK_TIME 문제를 기록합니다. 시간 기반 규칙은 해당 기록을 정상 시간으로 추정하지 않습니다.
- 거래 상한 때문에 범위를 모두 확인하지 못하면 PARTIAL + TRANSACTION_LIMIT입니다. 상한과 정확히 같다는 사실만으로 부분 여부를 추정하지 말고 페이지/이력 종료를 확인합니다.
- 조회한 거래나 레이블 일부를 보존할 수 있으면 PARTIAL과 issues를 반환합니다. 평가에 사용할 수 있는 Snapshot을 만들 수 없으면 구조화된 오류를 반환합니다.
- COMPLETE + transfers: []는 정상적인 빈 조회 성공입니다. 관측 전송이 없으면 observedRange는 null입니다. 조회 실패를 이 형태로 대체하지 않습니다.
- SANCTIONED는 제재 레이블, INCIDENT는 사고 연관 근거입니다. 둘을 같은 제재 신호로 취급하지 않습니다. 레이블 출처와 실제/합성 여부를 보존합니다.
- LIVE는 ON_CHAIN만 허용합니다. FIXTURE는 ON_CHAIN 또는 SYNTHETIC입니다. 합성 Snapshot의 네트워크 필드가 실제 관측을 의미하지 않습니다.

## KYT 예시 규칙

| kind | 의미 |
| --- | --- |
| SANCTION_ADDRESS_MATCH | 분석 지갑과 SANCTIONED 레이블 주소의 직접 일치 |
| SANCTION_DIRECT_TRANSFER | 분석 지갑이 참여한 성공 전송의 반대편 주소가 SANCTIONED이거나, 분석 지갑 자체가 SANCTIONED인 전송 |
| RAPID_FAN_OUT | 분석 지갑에서 나가는 양수 전송이 windowSeconds 이하의 시간창에서 minDistinctRecipients 이상의 고유 수신자에 도달 |

분산 송금은 `[start, start + windowSeconds]` 창으로 정의하며, 자산 종류와 무관한 전송 이벤트 수신자 수를 셉니다. 수량을 자산 간 합산하지 않습니다. 시간 미상 전송이 규칙 결과에 영향을 줄 수 있으면 해당 규칙을 unevaluatedRuleIds에 남깁니다. 제재 레이블 소스 실패도 관련 규칙을 미평가 처리합니다. 중복 finding으로 점수를 여러 번 올리지 않습니다.

예시 점수 집계는 `min(100, 탐지된 고유 활성 규칙의 scoreWeight 합)`입니다. `1 <= medium < high < critical <= 100` 순서를 런타임에 검사합니다. 임계값 이상부터 해당 등급이며 medium 미만은 LOW입니다. 예시값 30/60/90과 가중치 100/80/40은 법률·확률적 의미가 없는 데모 설정입니다.

하나라도 미평가 규칙이 있으면 이 초안에서는 riskLevel: UNKNOWN, riskScore: null로 반환합니다. 이미 확인한 findings는 보존합니다. coverageStatus는 수집 완전성으로 별도 유지합니다. COMPLETE 데이터라도 비지원 규칙 등으로 평가가 미완료일 수 있습니다. 0점과 UNKNOWN을 혼동하지 않습니다.

## Policy

- 송신자와 수신자의 고유 주소마다 최대 하나의 평가를 사용합니다. 같은 주소면 하나로 충분합니다. 요청과 관계없는 주소의 평가, 중복 주소 평가, 서로 다른 규칙 버전의 평가를 거부합니다.
- Public 요청의 analysisIds는 Backend가 저장된 평가로 해석합니다. 미완료 작업은 409입니다. 실패·누락으로 평가가 없으면 빈 evaluations를 넘겨 REVIEW 사유를 만듭니다. 없는 ID 자체는 404입니다.
- `asOf`는 Backend가 결정 시각으로 주입합니다. 평가 시각이 미래이면 요청을 거부하고, `asOf - evaluatedAt > maxEvaluationAgeSeconds`이면 STALE_EVALUATION으로 REVIEW합니다.
- 없는 평가, PARTIAL 데이터, UNKNOWN 위험은 각각 설정된 REVIEW 후보를 만듭니다. 완전하고 알려진 위험이면 riskActions에 따라 후보를 만듭니다.
- 최종 우선순위는 BLOCK > REVIEW > WARN > ALLOW입니다. 예를 들어 정상 송신자와 CRITICAL 수신자는 BLOCK, 정상 송신자와 불완전 수신자는 REVIEW입니다. 미완료 평가의 findings만으로 Policy가 점수를 재계산하지 않습니다.
- reasons에는 주소별 판단 근거를 남기며 적용된 evaluationIds·policyId·policyVersion을 기록합니다. decidedAt은 입력 asOf입니다.
- amountRaw는 양수입니다. 이 초안에서는 자산·수량별 정책이나 레이블 원본을 Policy에서 재조회하지 않습니다.

## Gateway

Gateway는 전달된 ComplianceDecision의 transferRequestId를 확인하고 결정을 그대로 적용합니다. Public API는 서버가 저장한 결정과 송금의 연결도 확인합니다. appliesPolicy는 경로 실험 조건이며 실제 RPC 사업자의 행위를 뜻하지 않습니다.

| appliesPolicy | decision | userConfirmedWarning | outcome | reasonCode |
| --- | --- | --- | --- | --- |
| false | 모든 값 | 모든 값 | SUBMITTED | POLICY_NOT_APPLIED |
| true | ALLOW | 모든 값 | SUBMITTED | POLICY_ALLOW |
| true | BLOCK | 모든 값 | REJECTED | POLICY_BLOCK |
| true | REVIEW | 모든 값 | HELD_FOR_REVIEW | POLICY_REVIEW |
| true | WARN | false | AWAITING_CONFIRMATION | WARNING_CONFIRMATION_REQUIRED |
| true | WARN | true | SUBMITTED | WARNING_CONFIRMED |

SUBMITTED는 모의 경로에 전달됐다는 의미입니다. networkSubmitted는 항상 false이며 실제 서명을 생성하거나 네트워크에 전송하지 않습니다. 결과의 routeId·policyApplied·decisionId로 적용 경로와 결정을 추적합니다.

## Constellation 추상 모델

정식 결과명은 `ConstellationSimulationResult`입니다. 기획의 `SimulationResult`는 같은 결과를 가리키는 축약 표현으로만 사용합니다.

이 초안에는 실제 프로토콜의 증명 정족수·암호학적 증명·네트워크 타이밍 규칙이 제공되지 않았습니다. 따라서 proof.conditionSatisfied를 독립적인 실험 입력으로 받습니다. 수락 제안자 수가 곧 증명 수라는 가정을 두지 않습니다. proof.assumption과 assumptionsVersion으로 이 한계를 기록합니다.

- 수락 제안자가 1개 이상이면 alternativeSubmissionPathExists: true입니다.
- 수락 제안자가 없는데 proof.conditionSatisfied: true이면 모순된 입력으로 400 INVALID_REQUEST입니다.
- 이 추상 모델은 수락 경로 존재 AND proof.conditionSatisfied일 때만 inclusionForced: true를 반환합니다.
- leaderCanExclude는 그 부정으로, 정족수 미확보 등에서는 리더가 제외할 수 있음을 뜻합니다. leaderAttemptsExclusion은 시도 여부이며 가능 여부를 바꾸지 않습니다.
- 단일 리더 비교 기준은 리더가 선택적으로 제외할 수 있는 이상화 모델이므로 singleLeaderCanExclude: true입니다. 실제 포함 여부를 예측하지 않습니다.
- 결과는 거래 성공, 네트워크 전체 차단, 실제 검열 저항성 수치 또는 제재 우회 성공률을 보장하지 않습니다. 실제 프로토콜 규칙 기반 모델로 확장할 때 출처·규칙·버전·Fixture를 함께 갱신합니다.

## 작업 상태와 오류

허용 전이는 QUEUED → RUNNING → COMPLETED / PARTIAL / FAILED 및 QUEUED → FAILED입니다. 종료 상태는 바뀌지 않습니다. 재시도는 새 analysisId로 추적합니다. RUNNING에서 Snapshot 일부를 공개하지 않고 최종 COMPLETED/PARTIAL에서 Snapshot과 Evaluation을 함께 제공합니다. 단순 HTTP 폴링은 중간 상태를 건너뛰어 관측할 수 있습니다.

| HTTP | error.code | 의미 |
| --- | --- | --- |
| 400 | INVALID_REQUEST / CONTRACT_VALIDATION_FAILED | 의미 오류 / JSON Schema 불일치 |
| 404 | NOT_FOUND | ID 또는 설정을 찾을 수 없음 |
| 409 | CONFLICT | 연결된 ID·버전·작업 상태 충돌 |
| 422 | UNSUPPORTED_VERSION | 지원하지 않는 schemaVersion |
| 429 | RATE_LIMITED | 요청 제한 |
| 500 | INTERNAL_ERROR | 내부 실행 실패 |
| 502 | UPSTREAM_UNAVAILABLE | 상위 데이터 제공자 실패 |
| 503 | UPSTREAM_UNAVAILABLE | 의존 서비스의 일시적 불가 |

schemaVersion 미지원은 다른 구조 오류보다 먼저 확인하여 422로 구분합니다. retryable은 상태 코드로 추측하지 말고 실제 원인에 따라 서버가 채웁니다. 작업 FAILED의 error는 동일 Error 객체이며 requestId는 작업 응답 최상위에 있습니다. 오류 메시지에 RPC 인증 토큰 등 비밀을 포함하지 않습니다.
