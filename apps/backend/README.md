# Backend API & Orchestrator

Frontend와 내부 모듈을 연결하고 분석 작업의 실행 순서·상태·결과를 관리합니다. (포트 8080)

- 흐름: 분석 작업 생성 → Collector 호출 → Snapshot 저장 → KYT 호출 → 평가 저장 → 조회 API,
  정책 심사 요청 시 Policy 호출, 실험 요청 시 Gateway·Simulator 호출
- 패키지: `analysis`(작업·상태), `compliance`(정책 심사 기록), `experiment`(실험), `upstream`(내부 모듈 클라이언트), `support`(계약 검증·오류 응답)
- 위험도·정책 결과를 계산하지 않으며, 내부 응답의 연결 관계를 검증한 뒤에만 노출합니다.
- `compliance.local-collector.enabled=true`: Collector 대신 `contracts/fixtures/{fixtureId}/snapshot.json` 사용 (로컬 개발 전용)

```bash
./mvnw -pl apps/backend spring-boot:run      # 또는 루트의 scripts/run-local.sh start
./mvnw -pl apps/backend test
```
