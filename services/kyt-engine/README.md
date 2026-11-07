# KYT Detection Engine

엔진 버전은 `kyt_engine.__version__`의 1.0.0, 데이터 계약은 0.1.0입니다. Ruleset 버전은 별도 관리하며 기본 등록 버전은 1.0.0입니다. 순수 분석 함수는 외부 RPC·DB 호출 없이 입력 Snapshot만 사용하고 원본 객체를 수정하지 않습니다.

저장소 루트에서 `python -m pip install -e '.[test]'`로 설치한 후 실행합니다.

```powershell
python -m kyt_engine --host 127.0.0.1 --port 8001
python -m kyt_engine --input contracts/fixtures/warn/evaluation-request.json
python -m pytest tests/kyt -q
```

설치된 `kyt-engine` 명령으로도 동일하게 실행할 수 있습니다. `--input -`는 UTF-8 JSON을 표준 입력에서 읽습니다. 성공은 JSON 응답과 종료 코드 0, 입력 오류는 표준 오류의 구조화된 JSON과 종료 코드 1입니다.

## HTTP

- `POST /internal/v1/kyt/evaluate`: KYTEvaluationRequest → KYTEvaluation
- `GET /health`: 서비스·엔진·스키마 버전과 상태

```powershell
$kytBody = Get-Content contracts/fixtures/warn/evaluation-request.json -Raw -Encoding UTF8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/internal/v1/kyt/evaluate -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($kytBody))
```

함수 호출은 `from kyt_engine import Detector; Detector().evaluate(request)`입니다. HTTP와 함수 호출 모두 공통 계약의 입력·출력·근거 참조를 검증합니다.

## 규칙

SANCTION_EXACT, SANCTION_DIRECT_FLOW, RAPID_FAN_OUT, RAPID_REPEAT를 지원합니다. 정의·점수·경계는 [공통 의미 규약](../../contracts/semantics.md)을 따릅니다. 부분 수집은 점수·등급을 null로 반환하면서 발견한 신호를 보존합니다. 불명확한 소유자를 토큰 계정 주소로 대신하여 패턴을 만들지 않습니다.

시간 규칙은 안정 정렬과 슬라이딩 창을 사용하며 각 규칙의 점수는 한 번만 합산합니다. 참조 ID와 배열 순서는 입력 순서와 무관하게 결정론적으로 생성됩니다. 순서는 signature·명령어 위치·전송 ID로 안정화하고 근거 ID는 의미 데이터의 SHA-256입니다.

새 규칙 설정은 `contracts/config/rulesets/`의 새 버전으로 등록하고 계약·테스트와 함께 배포합니다. 실행 중 클라이언트가 설정 전체를 주입하지 않습니다. 라이브러리의 `Detector(rulesets=...)`는 신뢰된 설정을 검증·복사하여 로드하는 구성 지점입니다. 미등록 버전은 422이며 자동 대체하지 않습니다.

HTTP 본문 기본 상한은 8 MiB이며 `--max-body-bytes`로 조정합니다. UTF-8 JSON, 단일 Content-Length를 요구하고 chunked 인코딩은 지원하지 않습니다. 중복 키·NaN·과도한 중첩·헤더/본문 requestId 불일치는 거부합니다. HTTP requestId는 1~128자의 공백 없는 출력 가능한 ASCII입니다. 오류는 공통 ErrorResponse이며 외부 제공자 데이터를 조회하거나 오류에서 비밀을 노출하지 않습니다.
