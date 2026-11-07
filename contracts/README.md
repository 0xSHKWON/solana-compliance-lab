# 공통 API 및 데이터 계약

- 프로젝트: 이상거래 — Solana 온체인 이상거래 탐지 및 컴플라이언스 통제 검증
- 근거 문서: 개발팀 공통 계약 Draft v2.1
- 계약 버전: `0.1.0` (SemVer, 협의용 초안)
- 범위: 오프체인 PoC. 메인넷은 조회만 하며 거래 전송·컨트랙트 배포는 지원하지 않습니다.

이 디렉터리가 모듈 간 계약의 단일 기준입니다. 제공 문서에서 확정하지 않은 필드, 엔드포인트, 점수·정책 설정은 이번에 제안한 초안입니다. 구현 착수 전 제공자와 소비자가 검토해야 합니다. 구현된 서비스나 승인된 법률 판단을 뜻하지 않습니다.

## 파일 구성

| 파일 | 내용 |
| --- | --- |
| `openapi.yaml` | OpenAPI 3.1 Public / Internal HTTP 계약 |
| `schemas/common.schema.json` | 주소, 수량, UTC 시각, 상태, 오류, 근거 참조 |
| `schemas/collector.schema.json` | 수집 요청, 정규화 전송, 레이블, 수집 범위, `KYTDataSnapshot` |
| `schemas/kyt.schema.json` | 규칙 설정, 평가 요청, `KYTEvaluation` |
| `schemas/policy.schema.json` | 가상 송금, 정책 설정, 판단 요청, `ComplianceDecision` |
| `schemas/experiment.schema.json` | Gateway 및 Constellation 요청·결과 |
| `schemas/api.schema.json` | Backend 작업 상태 및 Public 요청 |
| `config/` | 검증·시연용 규칙과 정책 예시 |
| `fixtures/manifest.json` | 각 Fixture와 검증할 스키마의 연결 |
| `semantics.md` | 스키마만으로 표현할 수 없는 의미·상태·참조 규칙 |
| `validate.py` | 스키마, OpenAPI, Fixture, 거부 사례 검증 |

JSON Schema는 2020-12를 사용합니다. 각 파일의 `$defs`에 요청·응답을 정의하며 OpenAPI가 이를 참조합니다. `common`과 `experiment`, `api` 파일 전체가 아니라 필요한 `$defs`를 선택해 검증합니다. `$id`는 식별용 네임스페이스이며 해당 URL에서 파일을 제공한다는 뜻은 아닙니다. 검증기는 로컬 스키마를 등록해야 합니다.

## 소유권과 경계

| 담당 | 모듈 | 제공하는 계약 |
| --- | --- | --- |
| 권상현 | Collector / Normalizer / Fixture Manager | `KYTDataSnapshot` |
| 정연한 | KYT Engine | `KYTEvaluation` |
| 정연한 | Policy Engine | `ComplianceDecision` |
| 최석훈 | Backend / Orchestrator | 분석 작업 및 `KYTAnalysisResult` |
| 최석훈 | Mock Gateway | `GatewayExperimentResult` |
| 최석훈 | Constellation Simulator | `ConstellationSimulationResult` |
| 최현수 | Frontend | Public API 소비 |

동일 담당자의 모듈도 책임을 분리합니다. Normalizer의 최종 출력을 Collector가 반환하며, Normalizer 자체의 원시 입력 형식은 Collector 내부 계약으로 남깁니다. Collector는 위험도를 계산하지 않고, KYT는 외부 API를 호출하지 않으며, Policy는 탐지를 다시 수행하지 않습니다. Gateway는 전달받은 정책 결정을 실행합니다. Backend는 실행을 연결하고 Frontend는 결과를 재계산하지 않습니다. 다른 모듈의 DB에 직접 접근하지 않습니다.

## API 사용 흐름

| 대상 | 메서드·경로 | 요청 → 응답 |
| --- | --- | --- |
| Public | `POST /api/v1/analyses` | `AnalysisRequest` → `202 AnalysisAccepted` |
| Public | `GET /api/v1/analyses/{analysisId}` | 작업 ID → `KYTAnalysisResult` |
| Public | `POST /api/v1/policy-decisions` | `PublicPolicyRequest` → `ComplianceDecision` |
| Public | `POST /api/v1/gateway-experiments` | `PublicGatewayRequest` → `GatewayExperimentResult` |
| Public | `POST /api/v1/constellation-simulations` | `SimulationRequest` → `ConstellationSimulationResult` |
| Internal | `POST /internal/v1/collector/snapshots` | `CollectionRequest` → `KYTDataSnapshot` |
| Internal | `POST /internal/v1/kyt/evaluations` | `EvaluationRequest` → `KYTEvaluation` |
| Internal | `POST /internal/v1/policy/decisions` | `DecisionRequest` → `ComplianceDecision` |
| Internal | `POST /internal/v1/gateway/experiments` | `GatewayRequest` → `GatewayExperimentResult` |
| Internal | `POST /internal/v1/constellation/simulations` | `SimulationRequest` → `ConstellationSimulationResult` |

Frontend는 Public API만 사용합니다. Backend는 분석 ID로 보관한 평가를 조회하고, 서버의 정책 ID·버전을 해석하여 Internal 요청을 구성합니다. Public Gateway 요청의 송금·결정 ID도 서버에 보관된 원본으로 해석합니다. 브라우저가 위험 점수, 정책 결정 또는 정책 설정을 직접 만들어 전달하지 않습니다.

Internal 경로는 서로 다른 서비스의 논리 경계입니다. 실제 호스트·포트는 배포 설정에서 지정합니다. 같은 프로세스에서 호출해도 동일한 요청·응답 스키마를 검증합니다. 내부 경로를 외부에 공개하지 않습니다. 인증·인가 방식은 이 초안에서 결정하지 않았으며 공개 배포 전에 별도로 정해야 합니다.

분석 접수 시 `Location: /api/v1/analyses/{analysisId}`를 반환합니다. 조회 시 작업이 존재하면 실패 작업도 HTTP 200으로 상태를 반환하며, 존재하지 않는 작업은 404입니다. 정책·Gateway·시뮬레이션은 이 초안에서 동기식 HTTP 200 응답입니다. 모든 실패 응답은 `ErrorResponse`를 사용합니다.

## 표기 및 버전

- 필드명은 camelCase, Enum은 UPPER_SNAKE_CASE입니다.
- 시각은 UTC ISO 8601의 `Z` 표현만 허용합니다. 조회 구간은 `[from, to)`입니다.
- 원시 수량은 최소 단위의 십진 정수 문자열입니다. `"1000000"`은 decimals가 6이면 1토큰입니다. `null`, `0`, `"0"`은 서로 다른 값입니다.
- 송금 요청 수량은 양수이며 정규화된 전송 기록에는 `"0"`을 허용합니다.
- SOL은 `mint: null`, `decimals: 9`입니다. SPL은 mint 주소와 decimals가 필요합니다. 심볼만으로 자산을 식별하지 않습니다.
- `schemaVersion`은 이 배포본에서 `0.1.0`만 받습니다. 규칙·정책·모델 버전은 별도 SemVer 필드입니다.
- `additionalProperties: false`를 적용합니다. 알 수 없는 필드·Enum과 생략된 필수 필드를 거부합니다.
- `null`은 명시적으로 허용된 필드에만 사용합니다. 빈 배열은 정상적인 빈 결과이며 조회 실패를 대신하지 않습니다.

## Fixture 사용

| 디렉터리 | 검증 의도 | 예시 정책 |
| --- | --- | --- |
| `normal/` | 정상·완전 데이터 | ALLOW |
| `sanctioned/` | 합성 제재 레이블과 직접 일치 및 직접 거래 | BLOCK |
| `warn/` | 단시간 분산 송금 및 경고 확인 전·후 Gateway | WARN |
| `partial/` | 레이블 소스 실패, 평가 불확실성 | REVIEW |
| `sender/` | 송신자의 별도 정상 분석 | ALLOW |
| `api/` | 대기·실행·실패, 빈 수집 성공, LIVE 요청, 오류 |
| `constellation/` | 증명 충족·미충족·전원 거절 |

**지금 포함된 주소, 서명, 레이블, 거래는 전부 합성 데이터입니다. 실제 제재 주소나 온체인 조회 결과가 아닙니다.** `SOLANA_MAINNET`은 주소·거래 형식의 대상 네트워크를 뜻하며 실제 데이터 여부는 `dataKind`로 구분합니다. `FIXTURE`에는 향후 실제 온체인 스냅샷도 포함할 수 있으므로 mode와 dataKind를 따로 보존합니다. `ON_CHAIN` Fixture 추가 시 실제 서명·출처와 외부 근거를 함께 보관해야 합니다.

`normal`, `sanctioned`, `warn`, `partial`의 송금은 공통 `sender/` 분석과 해당 수신자 분석을 사용합니다. Fixture의 `evaluatedAt`·`asOf`는 고정되어 있으며 현재 시각으로 바꾸지 않습니다. 모든 결과는 예시 설정의 기대값입니다. 실제 서비스 구현을 실행한 결과가 아닙니다.

## 검증 실행

저장소 루트에서 Python 3.11 이상을 사용합니다.

```powershell
python -m venv contracts/.venv
& contracts/.venv/Scripts/python.exe -m pip install -r contracts/requirements.txt
& contracts/.venv/Scripts/python.exe contracts/validate.py
```

macOS / Linux에서는 실행 파일 경로를 `contracts/.venv/bin/python`으로 바꿉니다. 검증 시 날짜·URI format 검사도 켜며, 저장소 스키마 참조는 로컬 파일로 해석합니다. 이 검증은 서비스의 실제 HTTP 구현·탐지 정확도·실제 네트워크를 테스트하지 않습니다.

## 변경 절차

1. 필수 필드·타입·Enum·의미·상태·오류 변경은 제공자와 소비자가 먼저 협의합니다.
2. 스키마·OpenAPI·Fixture·의미 설명·검증을 함께 수정합니다.
3. 모든 검증을 통과시킨 뒤 합의된 버전을 배포합니다. `0.x`에서도 호환성 변화를 문서화합니다.

참고 표준: [OpenAPI 3.1.0](https://spec.openapis.org/oas/v3.1.0.html), [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-core).
