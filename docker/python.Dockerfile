FROM python:3.12-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY services/engine-common services/engine-common
COPY services/kyt-engine services/kyt-engine
COPY services/policy-engine services/policy-engine
# Collector 패키지와 함께 fixtures·labels 데이터 파일이 필요하므로 디렉터리 전체를 복사합니다.
COPY services/collector services/collector
COPY contracts contracts
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

FROM base AS development
RUN pip install --no-cache-dir -e '.[test]'
COPY tests tests
COPY scripts scripts
USER app

FROM base AS runtime
RUN pip install --no-cache-dir .
USER app
