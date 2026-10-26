package com.example;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import no.entur.testcontainers.dockerfile.DockerfileImages;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.context.ImportTestcontainers;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.utility.DockerImageName;

@SpringBootTest
// Spring starts the containers below, so the log levels in application.properties apply. The class is named
// explicitly, otherwise all tests would share one cached Spring context and only the first one's containers.
@ImportTestcontainers(NginxIT.class)
class NginxIT {

	// image comes from src/test/resources/testcontainers/Dockerfile.nginx
	static GenericContainer<?> nginx = new GenericContainer<>(DockerImageName.parse(DockerfileImages.fromResource("testcontainers/Dockerfile.nginx"))).withExposedPorts(80);

	@Test
	void serves() throws Exception {
		var uri = URI.create("http://" + nginx.getHost() + ":" + nginx.getMappedPort(80) + "/");
		var response = HttpClient.newHttpClient().send(HttpRequest.newBuilder(uri).build(), HttpResponse.BodyHandlers.ofString());
		assertEquals(200, response.statusCode());
	}
}
