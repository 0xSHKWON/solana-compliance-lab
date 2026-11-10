package com.baypeline.backend.compliance;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Repository;

/** decisionId로 정책 심사 기록을 보관한다(메모리 저장소). */
@Repository
public class ReviewRepository {

    private final Map<String, ReviewRecord> records = new ConcurrentHashMap<>();

    public void save(ReviewRecord record) {
        records.put(record.decisionId(), record);
    }

    public Optional<ReviewRecord> find(String decisionId) {
        return Optional.ofNullable(records.get(decisionId));
    }
}
