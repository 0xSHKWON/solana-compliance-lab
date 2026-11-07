# 이상거래 — Solana Compliance Lab

실제 Solana 데이터의 위험 신호 탐지와 서비스 제출 경로의 컴플라이언스 통제 범위를 검증하는 오프체인 PoC입니다. 실제 거래 전송이나 스마트 컨트랙트 배포는 수행하지 않습니다.

현재 구현된 담당 모듈은 **KYT Detection Engine과 Compliance Policy Engine**입니다. Collector·Backend·Frontend·Gateway·Simulator는 다른 담당자의 구현 영역이며, 공통 계약과 합성 Fixture로 독립 개발할 수 있습니다.

## 설치와 실행

Python 3.11 이상이 필요합니다. 저장소 루트에서 실행합니다.

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -e '.[test]'

# 각각 별도 터미널에서 실행
& .venv/Scripts/python.exe -m kyt_engine --port 8001
& .venv/Scripts/python.exe -m policy_engine --port 8002
```

macOS/Linux에서는 `.venv/Scripts/python.exe`를 `.venv/bin/python`으로 바꿉니다. 각 서버는 기본적으로 127.0.0.1에 바인딩합니다. 같은 설치 안에 있지만 별도 프로세스에서 실행하며 서로를 호출하거나 import하지 않습니다.

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

공통 스키마·HTTP API는 [contracts/README.md](contracts/README.md), 개별 실행법은 [KYT](services/kyt-engine/README.md)와 [Policy](services/policy-engine/README.md)를 참고합니다. 위험 신호와 LOW 등급은 실제 불법성·적법성·안전성을 보증하지 않습니다. Constellation의 프로토콜 판정은 리서치 승인 후 별도로 구현하는 범위입니다.
