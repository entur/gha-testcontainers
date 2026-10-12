package com.example;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import no.entur.testcontainers.dockerfile.DockerfileImages;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

@Testcontainers
class NginxIT {

	// image comes from src/test/resources/testcontainers/Dockerfile.nginx
	@Container
	static GenericContainer<?> nginx = new GenericContainer<>(DockerImageName.parse(DockerfileImages.get("nginx"))).withExposedPorts(80);

	@Test
	void serves() throws Exception {
		var uri = URI.create("http://" + nginx.getHost() + ":" + nginx.getMappedPort(80) + "/");
		var response = HttpClient.newHttpClient().send(HttpRequest.newBuilder(uri).build(), HttpResponse.BodyHandlers.ofString());
		assertEquals(200, response.statusCode());
	}
}
