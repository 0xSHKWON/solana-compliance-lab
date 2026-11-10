package com.baypeline.backend.config;

import java.time.Clock;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.SyncTaskExecutor;
import org.springframework.core.task.TaskExecutor;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
@EnableConfigurationProperties(BackendProperties.class)
public class BackendConfig implements WebMvcConfigurer {

    private final BackendProperties properties;

    public BackendConfig(BackendProperties properties) {
        this.properties = properties;
    }

    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }

    /** 분석 작업 실행기. compliance.async=false 이면 요청 스레드에서 바로 실행한다(테스트용). */
    @Bean
    public TaskExecutor analysisExecutor() {
        if (!properties.async()) {
            return new SyncTaskExecutor();
        }
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("analysis-");
        executor.setCorePoolSize(properties.analysisWorkers());
        executor.setMaxPoolSize(properties.analysisWorkers());
        executor.setQueueCapacity(properties.analysisQueueCapacity());
        executor.initialize();
        return executor;
    }

    /** Frontend는 Public API만 호출한다. Internal 경로는 CORS를 열지 않는다. */
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOrigins(properties.corsAllowedOrigins().toArray(String[]::new))
                .allowedMethods("GET", "POST")
                .allowedHeaders("Content-Type", "X-Request-ID")
                .exposedHeaders("X-Request-ID", "Location");
    }
}
