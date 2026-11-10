# 이상거래 — Solana Compliance Lab

실제 Solana 데이터의 위험 신호 탐지와 서비스 제출 경로의 컴플라이언스 통제 범위를 검증하는 오프체인 PoC입니다. 실제 거래 전송이나 스마트 컨트랙트 배포는 수행하지 않습니다.

현재 **KYT Detection Engine, Compliance Policy Engine, Backend API, Mock Gateway, Constellation Simulator**가 구현되어 있습니다. Collector·Frontend는 다른 담당자의 구현 영역이며, 공통 계약과 합성 Fixture로 독립 개발할 수 있습니다.

## 모듈 구성

| 모듈 | 경로 | 포트 | 역할 |
| --- | --- | --- | --- |
| Backend API & Orchestrator | `apps/backend/` | 8080 | 분석 작업 상태 관리, 정책 심사 및 실험 API, 내부 모듈 호출 |
| Collector | `services/collector/` | 8000 | 수집 모듈 구현 영역. 로컬 통합 실행에서는 합성 fixture로 대체 |
| KYT Detection Engine | `services/kyt-engine/` | 8001 | 위험 신호 탐지 및 평가 |
| Compliance Policy Engine | `services/policy-engine/` | 8002 | 정책 결정 |
| Mock Gateway | `simulations/gateway/` | 8003 | 제출 경로의 정책 집행 재현 |
| Constellation Simulator | `simulations/constellation/` | 8004 | Constellation 초안·단일 리더 모델 비교 |

```text
Frontend ──▶ Backend (Public API, :8080)
               ├─▶ Collector       :8000  POST /internal/v1/collect
               ├─▶ KYT Engine      :8001  POST /internal/v1/kyt/evaluate
               ├─▶ Policy Engine   :8002  POST /internal/v1/policy/decide
               ├─▶ Mock Gateway    :8003  POST /internal/v1/gateway/experiment
               └─▶ Constellation   :8004  POST /internal/v1/constellation/simulate
```

Java 모듈과 빌드·실행 도구는 [baypeline/be](https://github.com/baypeline/be)의 `f469cd1c46640d4870f14f7490088dac589e1c0d` 커밋에서 가져왔습니다.

## Python 엔진 설치와 실행

Python 3.11 이상이 필요합니다. 저장소 루트에서 실행합니다.

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -e '.[test]'

# 각각 별도 터미널에서 실행
& .venv/Scripts/python.exe -m kyt_engine --port 8001
& .venv/Scripts/python.exe -m policy_engine --port 8002
```

macOS/Linux에서는 `.venv/Scripts/python.exe`를 `.venv/bin/python`으로 바꿉니다. 각 서버는 기본적으로 127.0.0.1에 바인딩합니다. 같은 설치 안에 있지만 별도 프로세스에서 실행하며 서로를 호출하거나 import하지 않습니다.

## 백엔드·시뮬레이터 설치와 실행

JDK 17 이상이 필요합니다. Java 모듈은 Spring Boot 3.5 기반이며, Maven은 루트의 Wrapper가 다운로드합니다. 모든 명령은 이 워크스페이스 루트에서 실행합니다.

```bash
# 모듈별로 별도 터미널에서 실행
./mvnw -pl apps/backend spring-boot:run
./mvnw -pl simulations/gateway spring-boot:run
./mvnw -pl simulations/constellation spring-boot:run
```

Windows PowerShell에서는 `./mvnw` 대신 `.\mvnw.cmd`를 사용합니다. Java 서버도 기본적으로 `127.0.0.1`에 바인딩합니다.

### 로컬 통합 실행 (macOS/Linux)

위 Python 엔진 설치를 마친 뒤 실행합니다. 별도 저장소를 클론할 필요 없이 현재 워크스페이스의 엔진과 공통 계약을 사용합니다.

```bash
scripts/run-local.sh start    # 빌드 후 KYT·Policy·Gateway·Constellation·Backend 기동
scripts/run-local.sh status   # /health 확인
scripts/run-local.sh stop     # 전체 종료
```

로그는 `.run/logs/`에 남습니다. Python 엔진은 현재 워크스페이스의 `.venv/bin/python`으로 실행하며, `LAB_DIR`로 다른 엔진·계약 경로를 지정할 수 있습니다.

로컬 통합 실행은 기본적으로 **fixture Collector**(`LOCAL_COLLECTOR_ENABLED=true`)를 사용합니다. `contracts/fixtures/{fixtureId}/snapshot.json`의 합성 데이터를 반환하며 FIXTURE 모드만 지원합니다. 실제 Collector를 연결할 때는 `LOCAL_COLLECTOR_ENABLED=false COLLECTOR_URL=http://... scripts/run-local.sh start`로 실행합니다. Backend를 개별 실행할 때 fixture Collector의 기본값은 `false`입니다.

## 파일 입력으로 실행

```powershell
& .venv/Scripts/python.exe -m kyt_engine --input contracts/fixtures/sanctioned/evaluation-request.json
& .venv/Scripts/python.exe -m policy_engine --input contracts/fixtures/sanctioned/policy-request.json
& .venv/Scripts/python.exe scripts/demo_engines.py --scenario sanctioned
& .venv/Scripts/python.exe scripts/demo_engines.py --scenario direct-flow --policy-version 1.1.0
```

데모는 실제 엔진을 순서대로 실행하여 평가·정책 결정과 계약 검증을 통과한 Gateway 요청을 출력합니다. Gateway 자체를 실행하거나 전송을 수행하지 않습니다. 모든 제공 Fixture는 합성 데이터입니다.

## 검증

```powershell
& .venv/Scripts/python.exe contracts/validate.py
& .venv/Scripts/python.exe -m pytest -q
# 모듈별 독립 테스트
& .venv/Scripts/python.exe -m pytest tests/kyt -q
& .venv/Scripts/python.exe -m pytest tests/policy -q
```

Java 모듈의 단위·API 테스트와 전체 흐름 검증은 다음 명령을 사용합니다.

```bash
./mvnw test
# scripts/run-local.sh start로 서비스를 실행한 상태에서 수행
.venv/bin/python scripts/e2e_smoke.py
```

`e2e_smoke.py`는 분석 → 거래 목록 → 정책 심사 → Gateway 결정 표 → Constellation → 오류 응답을 호출하고, 응답을 `contracts/runtime.py`의 JSON Schema로 검증합니다.

공통 스키마·HTTP API는 [contracts/README.md](contracts/README.md), 개별 실행법은 [KYT](services/kyt-engine/README.md), [Policy](services/policy-engine/README.md), [Backend](apps/backend/README.md), [Gateway](simulations/gateway/README.md), [Constellation](simulations/constellation/README.md)을 참고합니다. 위험 신호와 LOW 등급은 실제 불법성·적법성·안전성을 보증하지 않습니다. Constellation의 초안 모델은 구현되어 있지만 규칙과 임계값은 리서치팀 공식 확정 전입니다.

## Backend 호출 예시


```bash
# 1) 송신자·수신자 분석 (fixture 주소와 fixtureId가 일치해야 함)
curl -s -X POST localhost:8080/api/v1/analyses -H 'Content-Type: application/json' -d '{
  "address":"4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi","network":"mainnet-beta",
  "mode":"FIXTURE","fixtureId":"sender",
  "scope":{"fromTime":"2026-11-01T00:00:00Z","toTime":"2026-11-02T00:00:00Z","maxTransactions":100}}'
# → 202 {"analysisId":"analysis-...","status":"QUEUED"}  (recipient는 address 8qbHbw2…, fixtureId "sanctioned")

# 2) 상태·결과 조회, 거래 목록
curl -s localhost:8080/api/v1/analyses/{analysisId}
curl -s "localhost:8080/api/v1/analyses/{analysisId}/transfers?limit=100"

# 3) 거래 전 정책 심사 → decision.decisionId 획득
curl -s -X POST localhost:8080/api/v1/compliance/evaluate -H 'Content-Type: application/json' -d '{
  "intent":{"intentId":"demo-intent","network":"mainnet-beta",
    "sender":"4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi",
    "recipient":"8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
    "asset":{"type":"SOL","mint":null,"decimals":9},"amountRaw":"1000000000",
    "requestedAt":"2026-11-02T00:00:00Z"},
  "senderAnalysisId":"{sender}","recipientAnalysisId":"{recipient}","policyVersion":"1.0.0"}'

# 4) Gateway 실험 — 같은 결정을 정책 적용 / 미적용 경로로 비교
curl -s -X POST localhost:8080/api/v1/experiments/gateway -H 'Content-Type: application/json' -d '{
  "intentId":"demo-intent","decisionId":"{decisionId}",
  "route":{"routeId":"enforced","policyEnforced":true,"warningAcknowledged":false}}'
```

## Public API (Backend)

| Method | Endpoint | 설명 |
| --- | --- | --- |
| POST | `/api/v1/analyses` | 분석 시작 → 202 + `Location`. Collector → Snapshot 저장 → KYT → 평가 저장을 비동기로 실행 |
| GET | `/api/v1/analyses/{id}` | `QUEUED → RUNNING → COMPLETED / PARTIAL / FAILED`. FAILED도 200, 없는 ID는 404 |
| GET | `/api/v1/analyses/{id}/transfers` | `limit` 기본 100·최대 1000, 불투명 `cursor`. Snapshot 공개 전이면 409 `ANALYSIS_NOT_READY` |
| POST | `/api/v1/compliance/evaluate` | 저장된 두 분석으로 Policy Engine 호출. 미완료 409, 주소 불일치 409 `ASSESSMENT_MISMATCH` |
| POST | `/api/v1/experiments/gateway` | 저장된 심사 기록의 intent·decision으로 Gateway 호출. 없는 결정 404 |
| POST | `/api/v1/experiments/constellation` | 저장된 심사 기록 기준으로 Simulator 호출. 미승인 모델 422 |

모든 실패는 `{error: {code, message, retryable}, requestId}` 형식이며, 모든 응답에 `X-Request-ID`가 붙습니다.
클라이언트가 보낸 `X-Request-ID`가 있으면 그 값을 쓰고 내부 모듈에도 그대로 전달합니다.

## 설계 메모

- **책임 제한**: Backend는 위험도나 정책 결과를 계산하지 않고, Collector의 정규화 로직도 반복하지 않습니다.
  대신 내부 모듈 응답의 연결 관계를 확인한 뒤에만 저장·노출합니다(무검증 전달 금지).
  예를 들어 Snapshot의 주소·requestId·mode, 평가의 snapshotId·rulesetVersion, coverage와 점수 형태(PARTIAL → null)를 확인합니다.
- **브라우저 입력 불신**: Gateway·Constellation 요청은 `intentId`와 `decisionId`만 받습니다.
  원본 intent와 decision은 Backend에 저장된 심사 기록에서 가져옵니다.
- **Mock Gateway**: `contracts/semantics.md`의 결정 표를 그대로 구현했습니다.
  정책 미적용 경로는 action과 무관하게 `SUBMISSION_ALLOWED / POLICY_NOT_ENFORCED`를 반환해 우회 조건을 비교할 수 있습니다.
  `actualBroadcast`는 항상 `false`입니다.
- **Constellation Simulator**: 판정 모델을 버전으로 구분해 등록합니다. 요청의 `protocolModelVersion`으로 모델을 고릅니다.
  - `0.1.0-draft`: Constellation 규칙 초안입니다. 판정 순서는 제안자 경로 → pslice 가용성 → 증명 조건 → 리더 제외입니다.
    증명 비율이 임계값(기본 66.67%) 이상이면 포함이 강제되고, 이때 리더의 제외 시도는 무효입니다.
  - `0.1.0-single-leader`: 비교 기준인 기존 단일 리더 모델입니다. 포함 강제 장치가 없어서 리더의 제외가 항상 유효합니다.
  - 같은 시나리오를 두 버전으로 각각 호출해 통제 조건을 비교합니다. 같은 입력이면 항상 같은 결과가 나옵니다.
  - 정의상 모순(거절 수 > 전체, 수락 제안자가 없는데 수락 제안자에게 제출)은 모델과 무관하게 `INVALID_SCENARIO`로 응답합니다.
  - **주의**: `0.1.0-draft`의 규칙과 임계값은 팀 초안이며 리서치팀 공식 확정 전입니다.
    확정되면 `CONSTELLATION_ATTESTATION_THRESHOLD`나 새 `ProtocolModel` 버전으로 반영합니다.
    `contracts/config/protocol-models.json`(공통 계약)은 수정하지 않았습니다.
- **결정적 ID**: `experimentId`와 `simulationId`는 정렬된 의미 데이터의 SHA-256입니다(`contracts/runtime.py`의 `stable_id`와 같은 방식).
  같은 입력이면 requestId와 무관하게 같은 ID가 나옵니다.
- **저장소**: PoC라서 메모리 저장소(`AnalysisRepository`, `ReviewRepository`)를 씁니다. 재시작하면 기록이 사라집니다.
- **모듈 독립성**: Java 세 모듈은 독립적으로 실행·검증할 수 있도록 공통 지원 코드(`support/`)를 각자 가지고 있습니다.
  테스트 리소스의 `fixtures/`는 `contracts/fixtures`에서 복사한 합성 데이터입니다.

## 주요 설정 (환경 변수)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `BACKEND_PORT` / `GATEWAY_PORT` / `CONSTELLATION_PORT` | 8080 / 8003 / 8004 | 서버 포트 (기본 바인딩 127.0.0.1) |
| `COLLECTOR_URL` `KYT_URL` `POLICY_URL` `GATEWAY_URL` `CONSTELLATION_URL` | `http://127.0.0.1:8000~8004` | 내부 모듈 주소 |
| `DEFAULT_RULESET_VERSION` | `1.0.0` | 요청에 rulesetVersion이 없을 때 사용 |
| `LOCAL_COLLECTOR_ENABLED` / `LOCAL_COLLECTOR_FIXTURES_DIR` | `false` / `contracts/fixtures` | fixture Collector (run-local.sh는 true) |
| `CONSTELLATION_ATTESTATION_THRESHOLD` | `66.67` | 초안 모델의 포함 강제 증명 임계값(%, 이상) |
| `CONSTELLATION_MOCK_ENABLED` | `false` | mock 버전 응답 허용 (run-local.sh는 true) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Frontend 출처 |
