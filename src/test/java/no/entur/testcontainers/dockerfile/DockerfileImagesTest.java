package no.entur.testcontainers.dockerfile;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DockerfileImagesTest {

	@Test
	void parsesString() {
		assertEquals("redis:7.2", DockerfileImages.parse("FROM redis:7.2\n"));
	}

	@Test
	void parsesInputStream() {
		assertEquals("redis:7.2", DockerfileImages.parse(new ByteArrayInputStream("FROM redis:7.2".getBytes(StandardCharsets.UTF_8))));
	}

	@Test
	void parsesByteArray() {
		assertEquals("redis:7.2", DockerfileImages.parse("FROM redis:7.2".getBytes(StandardCharsets.UTF_8)));
	}

	@Test
	void parsesResource() {
		assertEquals("redis:7.2", DockerfileImages.fromResource("testcontainers/Dockerfile.redis"));
		assertEquals("redis:7.2", DockerfileImages.fromResource("/testcontainers/Dockerfile.redis"));
	}

	@Test
	void parsesResourceWithClassLoader() {
		assertEquals("redis:7.2", DockerfileImages.fromResource("testcontainers/Dockerfile.redis", getClass().getClassLoader()));
	}

	@Test
	void parsesDigestAndSkipsComments() {
		assertEquals("postgres@sha256:abc", DockerfileImages.fromResource("testcontainers/Dockerfile.postgres"));
	}

	@Test
	void parsesPathAndFile(@TempDir Path dir) throws IOException {
		Path dockerfile = Files.writeString(dir.resolve("Dockerfile.nginx"), "FROM nginx:1.27\n");
		assertEquals("nginx:1.27", DockerfileImages.fromPath(dockerfile));
		assertEquals("nginx:1.27", DockerfileImages.fromFile(dockerfile.toFile()));
	}

	@Test
	void missingResourceFails() {
		assertThrows(IllegalStateException.class, () -> DockerfileImages.fromResource("testcontainers/Dockerfile.missing"));
	}

	@Test
	void missingFileFails(@TempDir Path dir) {
		assertThrows(UncheckedIOException.class, () -> DockerfileImages.fromPath(dir.resolve("missing")));
	}

	@Test
	void noFromLineFails() {
		assertThrows(IllegalStateException.class, () -> DockerfileImages.parse("# nothing here\nRUN true\n"));
	}

	@Test
	void ignoresStageReferencesAndFlags() {
		assertEquals("alpine:3", DockerfileImages.parse("FROM --platform=$BUILDPLATFORM golang AS builder\nFROM builder AS x\nfrom alpine:3 as final\n"));
	}

	@Test
	void ignoresScratchAndVariables() {
		assertEquals("busybox", DockerfileImages.parse("FROM scratch\nFROM $BASE\nFROM busybox\n"));
	}

	@Test
	void handlesWindowsLineEndings() {
		assertEquals("redis:7.2", DockerfileImages.parse("# c\r\nFROM redis:7.2\r\n"));
	}
}
