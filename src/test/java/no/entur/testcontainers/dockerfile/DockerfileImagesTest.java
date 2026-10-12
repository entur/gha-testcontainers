package no.entur.testcontainers.dockerfile;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.StringReader;

import org.junit.jupiter.api.Test;

class DockerfileImagesTest {

	private static String parse(String dockerfile) throws IOException {
		return DockerfileImages.parse(new BufferedReader(new StringReader(dockerfile))).orElse(null);
	}

	@Test
	void readsDefaultLocation() {
		assertEquals("redis:7.2", DockerfileImages.get("redis"));
	}

	@Test
	void readsDigestAndSkipsComments() {
		assertEquals("postgres@sha256:abc", DockerfileImages.get("postgres"));
	}

	@Test
	void customDirectoryAndPrefix() {
		assertEquals("nginx:1.27", DockerfileImages.in("/docker/").withPrefix("Dockerfile-").image("nginx"));
	}

	@Test
	void missingFileFails() {
		assertThrows(IllegalStateException.class, () -> DockerfileImages.get("missing"));
	}

	@Test
	void ignoresStageReferencesAndFlags() throws IOException {
		assertEquals("alpine:3", parse("FROM --platform=$BUILDPLATFORM golang AS builder\nFROM builder AS x\nfrom alpine:3 as final\n"));
	}

	@Test
	void ignoresScratchAndVariables() throws IOException {
		assertEquals("busybox", parse("FROM scratch\nFROM $BASE\nFROM busybox\n"));
	}
}
