package com.baypeline.constellation;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Constellation Simulator: 제안된 프로토콜의 거래 포함 규칙을 버전별 모델로 시뮬레이션한다. */
@SpringBootApplication
public class ConstellationApplication {

    public static void main(String[] args) {
        SpringApplication.run(ConstellationApplication.class, args);
    }
}
