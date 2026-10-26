package com.example;

import static org.junit.jupiter.api.Assertions.assertTrue;

import no.entur.testcontainers.dockerfile.DockerfileImages;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.context.ImportTestcontainers;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.utility.DockerImageName;

@SpringBootTest
// Spring starts the containers below, so the log levels in application.properties apply. The class is named
// explicitly, otherwise all tests would share one cached Spring context and only the first one's containers.
@ImportTestcontainers(RedisIT.class)
class RedisIT {

	// image comes from src/test/resources/testcontainers/Dockerfile.redis
	static GenericContainer<?> redis = new GenericContainer<>(DockerImageName.parse(DockerfileImages.fromResource("testcontainers/Dockerfile.redis"))).withExposedPorts(6379);

	@Test
	void redisAnswersPing() throws Exception {
		assertTrue(redis.execInContainer("redis-cli", "ping").getStdout().contains("PONG"));
	}
}
