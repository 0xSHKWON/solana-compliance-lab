FROM maven:3.9-eclipse-temurin-17 AS development
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY pom.xml ./
COPY apps/backend apps/backend
COPY simulations/gateway simulations/gateway
COPY simulations/constellation simulations/constellation

FROM development AS build
# Build and test all three modules; Docker shares this layer between services.
RUN --mount=type=cache,target=/root/.m2 mvn -B -ntp package

FROM eclipse-temurin:17-jre-jammy AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
ARG MODULE=apps/backend
COPY --from=build /workspace/${MODULE}/target/*.jar /app/app.jar
COPY contracts/fixtures /app/contracts/fixtures
USER app
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
