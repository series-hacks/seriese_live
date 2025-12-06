import json
import logging
import signal
from typing import TYPE_CHECKING

from confluent_kafka import Consumer, KafkaError, KafkaException

if TYPE_CHECKING:
    from config import Config
    from handlers.message_handler import MessageHandler

logger = logging.getLogger(__name__)


class KafkaMessageConsumer:
    """Kafka consumer for Series API events."""

    def __init__(self, config: "Config", handler: "MessageHandler"):
        self.config = config
        self.handler = handler
        self.running = False
        self.consumer = None

        # Kafka configuration for Confluent Cloud
        self.kafka_config = {
            'bootstrap.servers': config.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': config.KAFKA_GROUP_ID,
            'client.id': config.KAFKA_CLIENT_ID,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'PLAIN',
            'sasl.username': config.KAFKA_SASL_USERNAME,
            'sasl.password': config.KAFKA_SASL_PASSWORD,
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000
        }

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def start(self):
        """Start consuming messages from Kafka."""
        self._setup_signal_handlers()
        self.running = True

        try:
            self.consumer = Consumer(self.kafka_config)
            self.consumer.subscribe([self.config.KAFKA_TOPIC])

            logger.info(f"Subscribed to topic: {self.config.KAFKA_TOPIC}")
            logger.info("Waiting for messages...")

            while self.running:
                msg = self.consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        # End of partition, not an error
                        logger.debug(f"Reached end of partition {msg.partition()}")
                    elif msg.error().code() == KafkaError._ALL_BROKERS_DOWN:
                        logger.error("All brokers are down, attempting to reconnect...")
                    else:
                        raise KafkaException(msg.error())
                    continue

                # Process message
                self._process_message(msg)

        except KafkaException as e:
            logger.error(f"Kafka error: {e}")
            raise
        finally:
            self.close()

    def _process_message(self, msg):
        """Process a single Kafka message."""
        try:
            value = msg.value()
            if value is None:
                return

            # Decode and parse message
            data = json.loads(value.decode('utf-8'))

            logger.debug(f"Received event: {data.get('event_type')}")

            # Pass to handler
            self.handler.handle_event(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def close(self):
        """Close the consumer connection."""
        if self.consumer:
            logger.info("Closing Kafka consumer...")
            self.consumer.close()
            self.consumer = None
            logger.info("Kafka consumer closed")
