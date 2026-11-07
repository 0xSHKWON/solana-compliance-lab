# Compliance Policy Engine

엔진 버전은 `policy_engine.__version__`의 1.0.0, 데이터 계약은 0.1.0입니다. 정책 버전 1.0.0과 1.1.0을 별도로 등록합니다. KYT 엔진을 import하거나 재실행하지 않고 주어진 평가를 검증하여 정책 결정만 반환합니다. RPC·DB 접근이나 거래 전송은 없습니다.

저장소 루트에서 `python -m pip install -e '.[test]'`로 설치한 후 실행합니다.

```powershell
python -m policy_engine --host 127.0.0.1 --port 8002
python -m policy_engine --input contracts/fixtures/sanctioned/policy-request.json
python -m pytest tests/policy -q
```

`policy-engine` 명령, `--input -` 표준 입력도 지원합니다. JSON 출력·종료 코드 규칙과 HTTP 본문·requestId 제한은 [KYT 실행 문서](../kyt-engine/README.md)와 같습니다.

## HTTP와 함수 API

- `POST /internal/v1/policy/decide`: PolicyDecisionRequest → ComplianceDecision
- `GET /health`: 서비스·엔진·스키마 버전과 상태
- `from policy_engine import PolicyEngine; PolicyEngine().decide(request)`

```powershell
$policyBody = Get-Content contracts/fixtures/direct-flow/block-policy-request.json -Raw -Encoding UTF8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/internal/v1/policy/decide -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($policyBody))
```

양쪽 평가의 주소·근거 참조·점수 기여도 일관성을 검증합니다. 같은 주소의 두 평가가 다르거나 동일 근거 ID의 내용이 충돌하면 거부합니다. 필수 평가 누락은 입력 오류이며 유효한 null 점수는 REVIEW 사유입니다.

## 정책

| 조건 | 정책 1.0.0 | 정책 1.1.0 |
| --- | --- | --- |
| 완전한 양쪽 평가, 탐지 없음 | ALLOW | ALLOW |
| 일반 위험 신호 | WARN | WARN |
| 불완전 평가 | REVIEW | REVIEW |
| 직접 제재 목록 일치 | BLOCK | BLOCK |
| 제재 주소와 직접 자금 이동 | REVIEW | BLOCK |

복수 사유의 우선순위는 BLOCK > REVIEW > WARN > ALLOW입니다. null 위험도는 결과에도 전파합니다. 전체 점수는 양쪽 점수의 최댓값이며 근거를 이중 합산하지 않습니다. HIGH 조치는 각 정책의 highRiskAction을 따릅니다.

decisionId는 원본 intent·정규화된 assessments·policyVersion의 SHA-256입니다. requestId나 배열 순서만 바뀌어도 동일한 결정을 반환합니다. evaluatedAt은 재현 가능한 기준 시각인 intent.requestedAt입니다. 실제 처리 시각과 평가의 신선도는 Backend가 보관·검증합니다.

출력은 공통 GatewayExperimentRequest의 decision으로 바로 사용할 수 있습니다. route의 적용·경고 확인과 실제 제출 여부를 판단하는 것은 Gateway의 책임입니다. 연결 예시는 `python scripts/demo_engines.py --scenario sanctioned`으로 확인할 수 있습니다.

정책은 `contracts/config/policies/`에 새 버전으로 추가합니다. 라이브러리의 `PolicyEngine(policies=...)`는 신뢰된 구성을 검증·복사하는 지점이며 HTTP 요청에서는 policyVersion만 받습니다. 미등록 정책·비지원 Ruleset 버전은 422로 반환하고 자동 대체하지 않습니다.
