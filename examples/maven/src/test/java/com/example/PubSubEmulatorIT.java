package com.example;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.google.pubsub.v1.PublisherGrpc;
import com.google.pubsub.v1.Topic;
import io.grpc.ManagedChannelBuilder;
import no.entur.testcontainers.dockerfile.DockerfileImages;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.context.ImportTestcontainers;
import org.testcontainers.gcloud.PubSubEmulatorContainer;
import org.testcontainers.utility.DockerImageName;

@SpringBootTest
// Spring starts the containers below, so the log levels in application.properties apply. The class is named
// explicitly, otherwise all tests would share one cached Spring context and only the first one's containers.
@ImportTestcontainers(PubSubEmulatorIT.class)
class PubSubEmulatorIT {

	// image comes from src/test/resources/testcontainers/Dockerfile.gcp-emulators
	static PubSubEmulatorContainer pubsub = new PubSubEmulatorContainer(DockerImageName.parse(DockerfileImages.fromResource("testcontainers/Dockerfile.gcp-emulators")));

	@Test
	void createsTopicOverGrpc() throws Exception {
		var channel = ManagedChannelBuilder.forTarget(pubsub.getEmulatorEndpoint()).usePlaintext().build();
		try {
			var topic = PublisherGrpc.newBlockingStub(channel).createTopic(Topic.newBuilder().setName("projects/example/topics/example").build());
			assertEquals("projects/example/topics/example", topic.getName());
		} finally {
			channel.shutdownNow();
		}
	}
}
