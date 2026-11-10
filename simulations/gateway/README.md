# Mock Gateway

리테일 서비스의 거래 제출 경로에서 정책이 어떻게 집행되는지 재현합니다. (포트 8003)
`POST /internal/v1/gateway/experiment`: GatewayExperimentRequest → GatewayExperimentResult

| policyEnforced | action | warningAcknowledged | outcome | reasonCodes |
| --- | --- | --- | --- | --- |
| false | * | * | SUBMISSION_ALLOWED | POLICY_NOT_ENFORCED |
| true | ALLOW | * | SUBMISSION_ALLOWED | POLICY_ALLOW |
| true | BLOCK | * | SUBMISSION_REJECTED | POLICY_BLOCK |
| true | REVIEW | * | REVIEW_REQUIRED | POLICY_REVIEW |
| true | WARN | false | REVIEW_REQUIRED | WARNING_NOT_ACKNOWLEDGED |
| true | WARN | true | SUBMISSION_ALLOWED | WARNING_ACKNOWLEDGED |

- 정책 결정을 다시 판단하지 않습니다. `intent.intentId`와 `decision.intentId`는 일치해야 합니다.
- 실제 네트워크에 송신하지 않습니다(`actualBroadcast: false`). 제출 허용은 실제 거래 포함을 뜻하지 않습니다.
- 외부 API·DB 호출이 없는 독립 계산 모듈입니다. `experimentId`는 입력 의미 데이터의 SHA-256입니다.

```bash
./mvnw -pl simulations/gateway spring-boot:run
./mvnw -pl simulations/gateway test     # contracts/fixtures/gateway 6개 시나리오 포함
```
