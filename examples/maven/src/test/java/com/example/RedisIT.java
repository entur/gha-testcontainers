package com.example;

import static org.junit.jupiter.api.Assertions.assertTrue;

import no.entur.testcontainers.dockerfile.DockerfileImages;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

@Testcontainers
class RedisIT {

	// image comes from src/test/resources/testcontainers/Dockerfile.redis
	@Container
	static GenericContainer<?> redis = new GenericContainer<>(DockerImageName.parse(DockerfileImages.get("redis"))).withExposedPorts(6379);

	@Test
	void redisAnswersPing() throws Exception {
		assertTrue(redis.execInContainer("redis-cli", "ping").getStdout().contains("PONG"));
	}
}
