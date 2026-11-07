# 이상거래 공통 계약

네 담당자의 모듈 명세와 개발팀 공통 계약 Draft v2.1을 통합한 **단일 초안 0.1.0**입니다. 이전에 생성한 초기 초안을 대체합니다. 별도 0.2.0 계약이나 구형 필드 호환 API를 두지 않습니다. 배포된 계약의 호환성을 보장하는 릴리스가 아니라 구현 전 공동 작업 기준을 정리한 것입니다.

## 기준과 담당

| 담당 | 책임 | 입출력 |
| --- | --- | --- |
| 권상현 | Collector, Normalizer, Fixture Manager | KYTCollectionRequest → KYTDataSnapshot |
| 정연한 | KYT Engine | KYTEvaluationRequest → KYTEvaluation |
| 정연한 | Policy Engine | PolicyDecisionRequest → ComplianceDecision |
| 최석훈 | Backend / Orchestrator | Public 요청·작업·저장 결과 관리 |
| 최석훈 | Mock Gateway | GatewayExperimentRequest → GatewayExperimentResult |
| 최석훈 | Constellation Simulator | ConstellationSimulationRequest → ConstellationSimulationResult |
| 최현수 | Frontend | Backend Public API 소비·시각화 |

각 모듈은 요청과 응답을 모두 검증합니다. 동일 담당자라도 책임을 분리합니다. Collector는 위험도를 계산하지 않고, KYT와 Policy는 RPC·DB에 접근하지 않습니다. Policy는 탐지 로직을 다시 실행하지 않으며 Gateway는 결정을 재판단하지 않습니다. Backend·Frontend도 엔진 결과를 임의 계산하지 않습니다. 실제 거래 전송이나 컨트랙트 배포는 지원하지 않습니다.

## 파일 구성

| 파일 | 역할 |
| --- | --- |
| `openapi.yaml` | OpenAPI 3.1: Public 6개, Internal 5개 API |
| `schemas/common.schema.json` | 네트워크·자산·주소·수량·UTC 시각·오류·공통 상태 |
| `schemas/collector.schema.json` | 수집 요청, NormalizedTransfer, AddressLabel, Snapshot |
| `schemas/kyt.schema.json` | 평가 요청·결과·규칙·근거 및 Ruleset 설정 |
| `schemas/policy.schema.json` | TransactionIntent, 정책 요청·결정 및 Policy 설정 |
| `schemas/experiment.schema.json` | Gateway·Constellation 요청·응답 |
| `schemas/api.schema.json` | Public 요청, 분석 조회·전송 페이지·심사 응답 |
| `config/rulesets/`, `config/policies/` | 버전으로 고정한 데모 규칙·정책 |
| `config/protocol-models.json` | 리서치 승인 모델 목록: 현재 없음 |
| `fixtures/manifest.json` | 모든 Mock JSON과 스키마 연결 |
| `semantics.md` | 런타임 제약, 위험 점수·정책·상태 의미 |
| `runtime.py`, `validate.py` | 구조·의미·참조·거부 사례 검증 |

JSON Schema 2020-12를 사용합니다. `$defs`를 선택해 검증하며 OpenAPI는 같은 스키마를 참조합니다. `$id` URL은 식별자이며 파일 호스팅을 뜻하지 않습니다. 제공한 검증기는 로컬 파일을 등록하므로 저장소 스키마를 인터넷에서 가져오지 않습니다.

## API 목록

| 대상 | 메서드·경로 | 요청 → 응답 |
| --- | --- | --- |
| Public | POST `/api/v1/analyses` | AnalysisRequest → 202 AnalysisAccepted |
| Public | GET `/api/v1/analyses/{id}` | 분석 ID → KYTAnalysisResult |
| Public | GET `/api/v1/analyses/{id}/transfers` | 분석 ID·cursor·limit → TransferPage |
| Public | POST `/api/v1/compliance/evaluate` | ComplianceRequest → ComplianceResponse |
| Public | POST `/api/v1/experiments/gateway` | GatewayRequest → GatewayExperimentResult |
| Public | POST `/api/v1/experiments/constellation` | ConstellationRequest → ConstellationSimulationResult |
| Internal | POST `/internal/v1/collect` | KYTCollectionRequest → KYTDataSnapshot |
| Internal | POST `/internal/v1/kyt/evaluate` | KYTEvaluationRequest → KYTEvaluation |
| Internal | POST `/internal/v1/policy/decide` | PolicyDecisionRequest → ComplianceDecision |
| Internal | POST `/internal/v1/gateway/experiment` | GatewayExperimentRequest → GatewayExperimentResult |
| Internal | POST `/internal/v1/constellation/simulate` | ConstellationSimulationRequest → ConstellationSimulationResult |

Frontend는 Public API만 호출합니다. Internal은 논리적인 서비스 경계이며 실제 호스트·포트는 배포 설정입니다. 단일 프로세스의 함수 호출도 동일한 입출력 스키마를 유지합니다. 인증·인가 방식은 별도 배포 설계 사항이며 Internal을 브라우저에 공개하지 않습니다.

Public 분석 요청에서 requestId는 Backend가 생성하거나 X-Request-ID를 사용합니다. Internal 요청은 본문 requestId가 필수이며 헤더도 제공하면 두 값이 일치해야 합니다. 오류 본문과 모든 HTTP 응답의 X-Request-ID로 요청을 추적합니다. 분석 접수는 Location 헤더로 조회 경로를 반환합니다.

## 명세의 빈 부분을 채운 제안 사항

다음 항목은 담당자 명세를 연결하기 위해 구체화한 초안입니다. 소비자와 함께 검토할 수 있도록 명시합니다.

| 항목 | 구체화 |
| --- | --- |
| 실제·합성 구분 | Snapshot에 필수 `dataProvenance: {dataType, source, reference}` 추가. FIXTURE는 실제 스냅샷과 합성 데이터를 모두 담을 수 있음 |
| AddressLabel 세부 필드 | address, network, type, source, referenceId. type은 SANCTIONED / INCIDENT / OTHER |
| 근거 세부 필드 | 원본 서명·전송 ID·관련 주소·레이블 참조와 Snapshot·레이블 데이터셋 출처 |
| Public 분석 응답 | 주소·상태·수집 범위·출처·KYT 결과를 반환. 전송 목록은 별도 페이지 API |
| Public 정책 요청 | intent와 senderAnalysisId·recipientAnalysisId·policyVersion. Backend가 저장된 평가를 조회하여 내부 요청을 구성 |
| Public 정책 응답 | 원본 intent, 사용한 assessments, decision을 함께 반환하여 화면에서 근거를 해석할 수 있음 |
| Public Gateway 요청 | intentId·decisionId·route. Backend가 원본 객체를 조회. 브라우저가 정책 결정을 만들어 보내지 않음 |
| 추가 Internal 경로 | Gateway의 `/experiment`, Simulator의 `/simulate`는 이번에 제안한 명칭 |
| LOW 의미 | 완전한 분석에서 탐지 없음·0점만 LOW. 양수 점수는 MEDIUM 또는 HIGH |
| 증명 규칙 | 임계값을 임의 확정하지 않음. 모델 버전 미등록 시 422 UNSUPPORTED_VERSION |

## 표기 규칙

- 필드명 camelCase, Enum UPPER_SNAKE_CASE, 네트워크는 `mainnet-beta`입니다.
- UTC ISO 8601의 `Z` 표현을 사용합니다. 조회 구간은 `[fromTime, toTime)`입니다.
- amountRaw는 십진 정수 문자열입니다. 지수·소수·선행 0을 금지합니다. 전송 이력은 `"0"`을 허용하며 송금 의도는 양수여야 합니다.
- SOL은 mint: null, decimals: 9입니다. SPL과 TOKEN_2022는 mint가 필수입니다. 소수나 JavaScript Number로 원시 수량을 변환하지 않습니다.
- null, 0, `"0"`, 빈 배열은 서로 다릅니다. riskScore: null은 0점이 아닙니다.
- schemaVersion은 이 초안에서 0.1.0입니다. 규칙·정책·모델 버전은 별도 SemVer로 관리합니다. labelDataset.version은 외부 데이터셋 식별 문자열입니다.
- 추가 필드·잘못된 Enum·필수 필드 생략은 거부합니다. 의미 검증과 참조 검증은 JSON Schema 검증 후 수행합니다.

## Fixture

모든 Fixture는 **합성 데이터**입니다. 실제 제재 주소나 실제 조회 결과가 아닙니다. 실제 메인넷 사례 2~3개 확보는 Collector/Fixture Manager 담당 산출물이며 이 계약 작업에서 완료했다고 주장하지 않습니다.

normal, empty, sanctioned, direct-flow, warn, repeat, partial, partial-sanctioned, unresolved, missing-time, spl, token-2022 사례를 제공합니다. sender는 공통 송신자 분석입니다. Gateway에는 ALLOW/BLOCK/REVIEW 및 WARN 확인 전·후와 정책 미적용 경로를 제공합니다. api에는 대기·실행·실패·페이지 예시가 있습니다.

Constellation의 mock 예시는 **화면·스키마 검증용 출력**입니다. `0.0.0-research-pending`은 실행 가능한 승인 모델이 아니며 100% 같은 입력으로 실제 판정 기준을 추론하면 안 됩니다. 프로토콜 판정 코드·정족수·단일 리더 비교 기준은 리서치팀과 Simulator 담당자가 공식 설계를 검토하여 등록합니다.

## 검증

저장소 루트에서 Python 3.11 이상으로 실행합니다.

```powershell
python -m venv contracts/.venv
& contracts/.venv/Scripts/python.exe -m pip install -r contracts/requirements.txt
& contracts/.venv/Scripts/python.exe contracts/validate.py
```

macOS/Linux는 실행 파일 경로를 `contracts/.venv/bin/python`으로 바꿉니다. 스키마·OpenAPI·전체 Fixture·예시 참조·시나리오 연결·잘못된 입력 거부를 검사합니다. 서비스 구현이나 실제 프로토콜을 실행하는 검증은 아닙니다.

필수 필드·타입·Enum·의미·상태·오류 변경은 제공자·소비자 협의 후 스키마·OpenAPI·Fixture·문서·테스트를 함께 수정합니다.
