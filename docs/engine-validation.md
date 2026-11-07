# KYT·Policy 구현 검증 기록

검증일: 2026-11-07. Python 3.14.5 / Windows에서 실행했습니다. 지원 Python 버전은 3.11 이상입니다.

## 요구사항별 근거

| 요구사항 | 구현·검증 근거 |
| --- | --- |
| 공통 Snapshot 입력 처리 | collector.schema.json의 SOL/SPL/TOKEN_2022, 소유자·계정·전송 위치·수집 범위 검증 및 유형별 Golden Fixture |
| 제재 직접 일치 | 거래가 없는 주소 일치 및 PARTIAL에서 발견한 일치 유지 테스트 |
| 제재 직접 자금 이동 | 입금·출금, 토큰 계정 제재·미확인 소유자, INCIDENT 제외·0원 제외 테스트 |
| 시간 패턴 2종 | Fan-out·Repeat, 시간창 경계, 동일 서명 복수 명령어 제외·자산별 반복 그룹 검사 |
| 점수·등급·근거 | 규칙 기여도 단회 합산·100점 상한·근거 타입·원본 서명·출처 참조 검증 |
| 불완전 데이터 | PARTIAL·소유자 미확인·시각 미확인에서 종합 점수와 등급 null, 확보한 신호 보존 |
| 결정론성·입력 보존 | 입력·설정 방어적 복사, 순서·requestId 변경에도 동일 결과, 슬라이딩 창과 별도 완전 탐색 비교 |
| 송신자·수신자 평가 검증 | 주소 연결·같은 주소 평가·필수 평가·근거 ID·점수 기여도 일관성 검증 |
| 정책 버전별 조치 | ALLOW/WARN/REVIEW/BLOCK, 직접 거래 REVIEW/BLOCK 버전 차이, 우선순위·HIGH 설정 테스트 |
| 판단 근거·정책 버전 | Golden 응답 전체 일치, 원본 근거 ID 참조, 버전 미등록 422 및 자동 대체 금지 |
| Gateway 연동 | 실제 HTTP KYT 결과 → 실제 HTTP Policy 결과 → GatewayExperimentRequest 계약 검증 |
| 모듈 경계 | 순수 호출 중 RPC·DB 접근 차단 테스트, Policy의 KYT 호출 차단, 서로 다른 프로세스의 독립 import·실행 |
| 독립 실행 | 각각 별도 프로세스로 HTTP 서버 기동·health 확인, 파일/표준 입력 CLI 실행 |
| HTTP 오류·반복 실행 | UTF-8·잘못된 JSON·중복 키·NaN·용량·깊이·버전·상관 ID·동시 요청 검증 |
| 설치 패키지 | Wheel 빌드 후 별도 가상환경에 설치하고 `-I` 모드에서 두 엔진의 실제 입력 처리 확인 |

## 실행 결과

- `python contracts/validate.py`: 스키마 6개, OpenAPI 작업 11개, Fixture 151개, 잘못된 입력 31개 및 시나리오 연결 검증 통과.
- `python -m pytest -q`: 97개 통과. KYT와 Policy는 각각 29개의 독립 테스트를 포함합니다.
- `python -m pip wheel . --no-deps`: 설치 가능한 Wheel 빌드 통과. 스키마와 버전 설정은 패키지에 포함합니다.
- 별도 가상환경에 Wheel 설치 후 두 CLI를 실행하여 제재 직접 일치 HIGH/100과 직접 거래 정책 1.1.0의 BLOCK 응답 확인.

이 기록은 합성 Fixture와 계약·규칙 동작에 대한 검증입니다. 실제 위험 사례의 탐지 성능, 실제 메인넷 결과, 실제 Gateway 실행 또는 Constellation 프로토콜 검증을 의미하지 않습니다. 데이터 수집과 해당 모듈 구현은 각 담당자의 후속 통합 범위입니다.
