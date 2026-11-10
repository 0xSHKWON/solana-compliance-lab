package com.baypeline.backend.analysis;

import java.util.Optional;

/** 분석 작업 저장소. PoC는 메모리 구현을 사용하며 DB 구현으로 교체할 수 있다. */
public interface AnalysisRepository {

    void save(AnalysisJob job);

    Optional<AnalysisJob> find(String analysisId);

    void delete(String analysisId);
}
