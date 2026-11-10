package com.baypeline.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Mock Gateway: 리테일 서비스의 거래 제출 경로에서 정책 집행을 재현한다. 실제 송신 없음. */
@SpringBootApplication
public class GatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
