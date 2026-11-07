# 초기 초안에서 통합 명세로 변경한 내용

네 담당자의 명세를 기준으로 초기 생성본을 수정했습니다. 버전별 계약을 병렬 유지하지 않으며 `contracts/`가 단일 기준입니다. 아직 초기 초안이므로 schemaVersion은 0.1.0을 유지합니다. 기존 초안의 필드와 API는 이 버전의 호환 인터페이스가 아닙니다.

| 영역 | 초기 생성본 | 통합 명세 |
| --- | --- | --- |
| 수집 API | `/internal/v1/collector/snapshots` | `/internal/v1/collect` |
| 수집 주소 | walletAddress | address |
| 네트워크 | SOLANA_MAINNET | mainnet-beta |
| 전송 | transferId·sender·recipient·blockTime | id·fromAddress·toAddress·timestamp 및 계정·명령어 위치 |
| 자산 | kind: SOL / SPL_TOKEN | type: SOL / SPL / TOKEN_2022 |
| 수집 범위 | requestedRange·issues | fromTime·toTime·reasons·snapshotSlot·집계·종료 경계 |
| KYT API | `/internal/v1/kyt/evaluations` | `/internal/v1/kyt/evaluate` |
| KYT 규칙 | 요청에서 RuleSet 전체 전달 | rulesetVersion으로 서버의 불변 설정 선택 |
| KYT 결과 | walletAddress·findings | subjectAddress·detectedRules·evidences |
| 위험 등급 | LOW / MEDIUM / HIGH / CRITICAL / UNKNOWN | LOW / MEDIUM / HIGH / null |
| Policy API | `/internal/v1/policy/decisions` | `/internal/v1/policy/decide` |
| 정책 입력 | transferRequest·evaluations·policy | intent·assessments.sender/recipient·policyVersion |
| 정책 출력 | decision·transferRequestId | action·intentId |
| Gateway | routes 배열, SUBMITTED 등 | 단일 route, SUBMISSION_ALLOWED / SUBMISSION_REJECTED / REVIEW_REQUIRED |
| 실제 송신 여부 | networkSubmitted | actualBroadcast: false |
| Simulator | 임의 증명 조건·제안자 목록 | protocolModelVersion·scenario·pslice·attestationPercent |
| Public 정책 API | `/api/v1/policy-decisions` | `/api/v1/compliance/evaluate` |
| Public 실험 API | gateway-experiments / constellation-simulations | `/api/v1/experiments/gateway` / `constellation` |

규칙·정책의 기본 수치는 config의 예시 버전으로 관리합니다. Constellation 모델은 리서치팀 확정 전까지 승인 목록을 비워 둡니다. 세부 보완 제안과 각 필드의 의미는 README.md와 semantics.md를 참고합니다.
