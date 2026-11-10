# Collector

Collector는 Backend의 분석 요청을 받아 Solana 메인넷 주소의 거래 이력을 수집·정규화하고, 위험 신호 탐지 엔진(KYT)이 사용할 `KYTDataSnapshot`을 만듭니다. 위험도나 정책 결정은 계산하지 않습니다. 엔진 버전은 `collector.__version__`의 0.1.0이며, 데이터 계약은 `contracts/schemas/collector.schema.json`을 따릅니다.

수집은 요청 시점에만 실행되는 온디맨드 방식입니다. 주소를 계속 감시하거나 새 거래를 자동으로 가져오지 않습니다. 요청마다 상태를 유지하지 않습니다.

## 모듈 구성

| 모듈 | 파일 | 역할 |
| --- | --- | --- |
| On-Demand Collector | `src/collector/service.py`, `live.py`, `rpc.py` | 요청 검증, LIVE/FIXTURE 분기, Solana JSON-RPC 조회(finalized), 스냅샷 조립 |
| Normalizer | `src/collector/normalizer.py` | jsonParsed 거래 결과 → 정규화된 전송(NormalizedTransfer). I/O 없는 순수 함수 |
| Fixture Manager | `src/collector/fixtures.py`, `labels.py` | 저장된 스냅샷을 요청 구간에 맞게 재구성(FIXTURE), 제재 라벨 데이터셋 로드 |
| 보조 도구 | `ofac.py`, `capture.py` | OFAC SDN 라벨 갱신, LIVE 수집 결과를 재현 가능한 FIXTURE로 기록 |

## 설치와 실행

저장소 루트에서 Python 3.11 이상으로 설치합니다. `collector` 명령과 `python -m collector`는 같은 진입점입니다.

```bash
python -m pip install -e '.[test]'

python -m collector --host 127.0.0.1 --port 8000
python -m collector --input contracts/fixtures/normal/collection-request.json
python -m collector --input -   # 표준 입력에서 JSON 읽기
python -m pytest tests/collector -q
```

`--input`은 요청 파일 하나를 처리하고 결과 JSON을 출력한 뒤 종료합니다. 성공하면 종료 코드 0, 입력 오류는 표준 오류에 구조화된 JSON을 출력하고 종료 코드 1입니다. 기본 바인딩은 `127.0.0.1`이며 포트 기본값은 8000입니다. Docker 개발 환경에서는 `compose.dev.yaml`이 `collector` 서비스로 실행하며 호스트의 `127.0.0.1:8000`에 노출됩니다.

## HTTP

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/internal/v1/collect` | `KYTCollectionRequest` → `KYTDataSnapshot`. 내부 모듈 전용이며 Backend만 호출합니다. |
| GET | `/health` | 서비스·엔진·스키마 버전과 상태 |

```bash
curl -s -X POST http://127.0.0.1:8000/internal/v1/collect \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @contracts/fixtures/normal/collection-request.json
```

요청 본문 상한은 기본 8 MiB이며 `--max-body-bytes`로 조정합니다. 요청과 응답은 모두 공통 계약으로 검증합니다. 요청에 `mode`, `address`, `network`, `scope`(fromTime < toTime, maxTransactions)가 있어야 하며, `scope.maxTransactions`는 `COLLECTOR_MAX_TRANSACTIONS`(기본 1000)를 넘을 수 없습니다. `scope.fromTime`이 현재 시각보다 미래이면 LIVE 요청을 거부합니다.

## 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SOLANA_RPC_URL` | 없음 | LIVE 모드의 Solana JSON-RPC 주소. 없으면 LIVE 요청은 503 `UPSTREAM_UNAVAILABLE`로 실패합니다. |
| `SOLANA_RPC_API_KEY` | 없음 | 선택. 설정하면 `SOLANA_RPC_API_KEY_HEADER` 헤더로만 전송합니다. |
| `SOLANA_RPC_API_KEY_HEADER` | `X-API-KEY` | API 키를 담는 HTTP 헤더 이름. Nodit 형식은 기본값을 사용합니다. |
| `SOLANA_RPC_PROVIDER` | `SOLANA_RPC` | 스냅샷 `dataProvenance.source`에 기록되는 제공자 이름. 예: `NODIT_SOLANA_RPC` |
| `SOLANA_RPC_TIMEOUT` | `15` | RPC 요청 제한 시간(초) |
| `SOLANA_RPC_MAX_TX_VERSION` | `1` | `getTransaction`의 `maxSupportedTransactionVersion`. 메인넷에는 v1 거래가 있으므로 기본값을 1로 둡니다. |
| `COLLECTOR_MAX_TRANSACTIONS` | `1000` | 요청 `maxTransactions`의 상한 |
| `COLLECTOR_LABEL_DATASET` | `services/collector/data/labels/ofac-sdn.json` | 제재 라벨 데이터셋 경로 |
| `COLLECTOR_FIXTURE_ROOTS` | `services/collector/fixtures`, `contracts/fixtures` | FIXTURE 조회 경로 목록. OS 경로 구분자(Linux `:`, Windows `;`)로 구분하며 앞의 경로가 우선합니다. |

## 모드별 동작

**FIXTURE** (`mode: "FIXTURE"`, `fixtureId` 필수)는 저장된 스냅샷을 읽습니다. 조회 순서는 `services/collector/fixtures/<id>/snapshot.json`(실제 메인넷 수집)이 먼저이고, 없으면 `contracts/fixtures/<id>/snapshot.json`(합성 데이터)입니다. 요청 주소가 스냅샷 주소와 다르면 409 `CONFLICT`입니다.

- 요청 구간과 수집 구간이 같고 거래 수가 `maxTransactions` 이하이면 스냅샷을 그대로 반환하며 `requestId`와 `mode`만 요청에 맞춥니다.
- 다르면 전송의 시각을 `[fromTime, toTime)`으로 다시 거르고, 거래 서명 수가 `maxTransactions`를 넘으면 최신 거래부터 남깁니다. 이때 `TRANSACTION_LIMIT_REACHED`가 추가됩니다.
- 요청 구간이 수집 구간을 벗어나면 `TIME_BOUNDARY_NOT_REACHED`가 추가됩니다.
- 시각을 알 수 없는 전송은 요청 구간이 수집 구간 전체를 덮을 때만 포함하며, 그 밖에는 `TIMESTAMP_UNAVAILABLE`로 완전성을 증명하지 않습니다.
- 입력 파일이나 저장된 스냅샷은 수정하지 않고 복사본을 만듭니다.

**LIVE** (`mode: "LIVE"`)는 Solana JSON-RPC로 조회합니다. 순서는 다음과 같습니다.

1. 라벨 데이터셋을 먼저 읽습니다. 실패하면 RPC를 호출하지 않고 503을 반환합니다.
2. `getSlot`(finalized)으로 기준 슬롯을 고정합니다.
3. `getSignaturesForAddress`를 finalized 기준으로 최신부터 1000개씩 페이지 조회합니다. 기준 슬롯보다 높은 서명과 `toTime` 이후 서명은 건너뜁니다.
4. `fromTime`보다 이전 `blockTime`을 만나거나 이력의 끝에 도달하면 중단합니다. `maxTransactions`개를 채운 뒤에도 구간 안의 서명이 남아 있으면 중단하고 `TRANSACTION_LIMIT_REACHED`를 기록합니다.
5. 서명마다 `getTransaction`(jsonParsed, finalized)을 호출합니다. 실패한 거래는 `transactionCount`에는 포함되지만 전송 계산에서는 제외합니다.
6. 거래를 정규화하여 전송을 모으고, 주소와 관련된 주소에 대해서만 라벨을 붙입니다.

RPC 호출은 재시도 가능 오류(JSON-RPC `-32005`, `-32429`, `-32603`, 네트워크 오류)에 대해 최대 3회 지수 백오프로 재시도합니다. 개별 거래 조회가 최종 실패하면 해당 거래를 건너뛰고 `TRANSACTION_FETCH_FAILED`를 기록합니다. 페이지네이션이 진전하지 않으면 502로 실패합니다.

스냅샷의 `dataProvenance.reference`는 항상 `null`입니다. RPC 주소에 API 키가 포함될 수 있기 때문입니다.

## 커버리지 사유

`coverage.status`는 사유가 하나라도 있으면 `PARTIAL`, 없으면 `COMPLETE`입니다. 사유는 계약의 `CoverageReason` 열거형을 따르며 KYT는 `PARTIAL`일 때 점수와 등급을 null로 반환합니다.

| 사유 | 발생 조건 |
| --- | --- |
| `TRANSACTION_LIMIT_REACHED` | `maxTransactions`를 채운 뒤에도 요청 구간 안의 거래가 남아 있음 (LIVE). 최신 거래만 남긴 경우 (FIXTURE). |
| `TIME_BOUNDARY_NOT_REACHED` | 요청 구간의 시작 시각까지 확인하지 못함. FIXTURE에서는 요청 구간이 수집 구간을 벗어날 때 발생합니다. |
| `TRANSACTION_FETCH_FAILED` | `getTransaction`이 재시도 후에도 실패하여 해당 거래를 가져오지 못함 |
| `UNSUPPORTED_INSTRUCTION` | 추적 대상 프로그램의 명령어이지만 파싱된 데이터가 없음 |
| `PARSE_FAILED` | 전송으로 보이는 명령어 또는 내부 명령어 그룹을 안전하게 읽을 수 없음 |
| `OWNER_UNRESOLVED` | 전송의 송신자 또는 수신자 소유자를 토큰 잔액에서 확인하지 못함. 해당 전송은 `ownerResolved: false`입니다. |
| `TIMESTAMP_UNAVAILABLE` | 거래의 `blockTime`이 없어 전송 시각을 알 수 없음 |
| `LABEL_DATASET_UNAVAILABLE` | 열거형에는 정의되어 있으나 현재 구현에서는 사유로 기록하지 않습니다. 라벨 데이터셋을 읽지 못하면 사유 대신 503 `UPSTREAM_UNAVAILABLE`로 응답합니다. |

## 정규화 규칙 요약

- 실패한 거래(`meta.err`가 있음)는 전송을 만들지 않습니다. 개수는 `transactionCount`에만 반영합니다.
- 전송으로 추적하는 명령어는 System Program의 `transfer`, `transferWithSeed`와 Token·Token-2022 프로그램의 `transfer`, `transferChecked`, `transferCheckedWithFee`입니다. 최상위 명령어와 내부 명령어를 모두 검사합니다.
- 조회 주소가 송신자·수신자의 소유자 또는 계정 주소에 있는 전송만 남깁니다.
- SOL은 9 decimals, 토큰은 잔액 정보의 mint와 decimals를 사용합니다. 금액은 원시 정수 문자열(`amountRaw`)로 보존합니다.
- 시각은 `blockTime`을 UTC `Z` 형식으로 변환합니다.
- 전송 ID는 서명, 명령어 위치, 내부 명령어 위치, 전송 순번을 해시한 값입니다. 결과 순서는 슬롯, 서명, 명령어 위치로 정렬하므로 같은 입력에 같은 결과를 냅니다.
- 같은 명령어에서 나온 중복 전송은 한 번만 기록합니다.

## 제재 라벨

라벨은 OFAC SDN 공식 목록의 "Digital Currency Address - SOL" 항목만 사용합니다. 주소가 정확히 일치하는 경우에만 `SANCTIONED` 라벨을 붙이며, `referenceId`는 SDN 항목 UID(`OFAC-SDN-<uid>`)입니다. 부분 일치, 유사 주소 추정, 다른 출처의 라벨은 사용하지 않습니다. 라벨 일치는 위험 신호이며 법적 판단이 아닙니다.

현재 데이터셋(`services/collector/data/labels/ofac-sdn.json`)의 출처 버전은 `2026-11-09`이고 SOL 주소는 4개입니다.

### 데이터셋 갱신

```bash
python -m collector.ofac                          # OFAC에서 SDN.XML을 내려받아 기본 경로에 저장
python -m collector.ofac --input SDN.XML          # 미리 받아 둔 파일로 오프라인 갱신
python -m collector.ofac --output /path/to/file.json
```

## Fixture 기록 (capture)

LIVE 수집 결과를 재현 가능한 FIXTURE로 저장합니다. 아래 실제 메인넷 Fixture는 같은 형식(스냅샷, 요청, RPC 기록, 근거 파일)으로 저장되어 있습니다.

```bash
SOLANA_RPC_URL=... SOLANA_RPC_API_KEY=... SOLANA_RPC_PROVIDER=NODIT_SOLANA_RPC \
python -m collector.capture --fixture-id mainnet-normal-wallet \
  --address 6UuyGCx5J5WjL1oiMnWAEoqGX6iNM2TcG6DUtjyr8NTA \
  --from 2026-10-01T00:00:00Z --to 2026-11-10T00:00:00Z --max 50 \
  --description "실제 메인넷 저활동 지갑 샘플"
```

`--output-root`를 생략하면 `services/collector/fixtures/<fixture-id>/`에 다음 파일을 씁니다.

- `snapshot.json`: 실제 LIVE 결과를 FIXTURE 모드로 표기한 스냅샷
- `collection-request.json`: 이 스냅샷을 FIXTURE 모드로 불러오는 요청
- `rpc-recording.json`: 호출한 RPC 메서드와 결과. 네트워크 없이 같은 정규화를 재현할 수 있습니다.
- `source.json`: 탐색기 링크, 라벨 데이터셋 버전, 캡처 설명 등 외부 근거

## Fixture 목록

실제 메인넷 Fixture는 `services/collector/fixtures/`에 있고, 합성 Fixture는 `contracts/fixtures/`에 있습니다. 같은 ID가 있으면 실제 Fixture가 우선합니다.

| fixtureId | 데이터 구분 | 주소 | 요청 구간 / maxTransactions | 수집 결과 | KYT 결과 |
| --- | --- | --- | --- | --- | --- |
| `mainnet-normal-wallet` | 실제 메인넷 (NODIT_SOLANA_RPC) | `6UuyGC…NTA` | 2026-10-01 ~ 2026-11-10 / 50 | COMPLETE, 거래 12건·전송 12건 (SOL, USDC, USDT) | LOW |
| `mainnet-ofac-sdn-exact` | 실제 메인넷, OFAC SDN 일치 | `42RLPA…oHi` | 2026-01-01 ~ 2026-11-10 / 50 | COMPLETE, 거래 5건·전송 0건 (토큰 계정 생성·동결 명령어만) | SANCTION_EXACT, HIGH |
| `mainnet-busy-wallet-partial` | 실제 메인넷 (활동량 많음) | `EnKfhn…VNL9` | 2026-11-01 ~ 2026-11-10 / 20 | PARTIAL (`TRANSACTION_LIMIT_REACHED`), 거래 20건 | 점수 null |
| `sender`, `sanctioned`, `normal`, `warn`, `partial`, `partial-sanctioned`, `repeat`, `direct-flow`, `spl`, `token-2022`, `unresolved`, `missing-time`, `empty` | 합성 (`contracts/fixtures`) | 합성 주소 | 각 `collection-request.json` 참고 | 계약 검증용 시나리오 | 시나리오별 |

합성 Fixture는 모두 합성 데이터이며 실제 주소나 실제 조회 결과가 아닙니다. 계약 검증용 목록은 `contracts/fixtures/manifest.json`에 있습니다. 실제 메인넷 Fixture의 주소는 공개된 블록체인 주소이며, 위험 신호는 법적 판단이 아닙니다.

## API 키 처리

- API 키는 `SOLANA_RPC_API_KEY` 환경 변수로만 받으며, 요청 헤더(`SOLANA_RPC_API_KEY_HEADER`)로만 전송합니다.
- 코드, 로그, 예외 메시지, `repr`, 스냅샷, `rpc-recording.json`, `source.json`에 기록하지 않습니다. RPC 주소도 예외 메시지에 넣지 않습니다.
- 저장소에는 키를 두지 않습니다. `.env`와 `.env.prod`는 `.gitignore`에 포함되며, `.env.example`과 `.env.prod.example`의 키 항목은 빈 값입니다.
- 실제 키는 로컬 `.env` 또는 운영 환경의 비밀 값 관리에만 둡니다.

## 한계

- **지갑 주소 조회의 누락 가능성**: `getSignaturesForAddress(wallet)`은 지갑 주소가 계정 키에 없고 지갑의 토큰 계정만 건드린 거래를 반환하지 않습니다. 이런 전송은 수집되지 않으며, 커버리지 사유로도 표시하지 않습니다.
- **추출 범위**: 전송으로 추적하는 명령어는 위에 나열한 것뿐입니다. 스왑, 임의 프로그램 호출, 메시지 내부의 간접 전송은 분석하지 않습니다.
- **실패 거래**: 실패한 거래는 `transactionCount`에 포함되지만 전송 계산에서는 빠집니다.
- **지속 감시 없음**: 요청 시점의 스냅샷만 만듭니다. 새 거래를 자동으로 수집하거나 알림을 보내지 않습니다.
- **확정성**: `finalized` 커밋먼트만 사용합니다. 아직 확정되지 않은 최근 거래는 포함되지 않습니다.
- **라벨 범위**: OFAC SDN의 SOL 주소만 사용합니다. 다른 제재 목록, 거래소 태그, 사용자 신고 정보는 없습니다. 데이터셋 갱신 주기는 운영자가 관리합니다.
- **FIXTURE 재구성**: 저장된 스냅샷에서 전송을 걸러 다시 만드는 방식이므로, 저장 시점에 누락된 거래는 복원할 수 없습니다.

## 운영 참고

- 개발 Compose에서는 `services/`와 `contracts/`를 읽기 전용으로 마운트하므로 Fixture와 라벨 데이터를 그대로 사용합니다.
- 운영 이미지는 `pip install .`로 설치합니다. Fixture와 라벨 데이터는 패키지 밖(`services/collector/fixtures`, `services/collector/data`)에 있어 설치되지 않으므로, 이미지에 디렉터리를 복사하고 `compose.prod.yaml`에서 `COLLECTOR_FIXTURE_ROOTS`와 `COLLECTOR_LABEL_DATASET`을 `/app` 아래 절대 경로로 지정합니다.
- 운영 Collector는 호스트 포트를 노출하지 않으며, Compose 네트워크에서 `http://collector:8000`으로 접근합니다. 읽기 전용 파일시스템과 일반 사용자(UID 10001)로 실행합니다.

## 테스트

```bash
python -m pytest tests/collector -q
```

Docker 개발 환경에서는 `docker compose -f compose.dev.yaml exec -T collector python -m pytest tests/collector -q`로 실행합니다.
