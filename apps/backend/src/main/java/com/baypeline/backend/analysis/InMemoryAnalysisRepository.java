package com.baypeline.backend.analysis;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Repository;

/** 프로세스 메모리 저장소. 재시작하면 작업 기록이 사라진다. */
@Repository
public class InMemoryAnalysisRepository implements AnalysisRepository {

    private final Map<String, AnalysisJob> jobs = new ConcurrentHashMap<>();

    @Override
    public void save(AnalysisJob job) {
        jobs.put(job.analysisId(), job);
    }

    @Override
    public Optional<AnalysisJob> find(String analysisId) {
        return Optional.ofNullable(jobs.get(analysisId));
    }

    @Override
    public void delete(String analysisId) {
        jobs.remove(analysisId);
    }
}
