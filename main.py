import logging
import sys

from config import Config
from consumers.kafka_consumer import KafkaMessageConsumer
from services.series_api import SeriesAPI
from services.twilio_service import TwilioService
from handlers.message_handler import MessageHandler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    # Load configuration
    config = Config()

    # Validate required config
    missing = config.validate()
    if missing:
        logger.error(f"Missing required configuration: {', '.join(missing)}")
        sys.exit(1)

    # Initialize Series API
    series = SeriesAPI(
        config.SERIES_API_KEY,
        config.SERIES_BASE_URL,
        config.SERIES_SENDER_NUMBER
    )

    # Initialize Twilio (optional - may not be configured)
    twilio = None
    if config.is_twilio_configured():
        twilio = TwilioService(
            config.TWILIO_ACCOUNT_SID,
            config.TWILIO_AUTH_TOKEN,
            config.TWILIO_PHONE_NUMBER
        )
        logger.info("Twilio service initialized")
    else:
        logger.warning("Twilio not configured - conference calls disabled")
        # Create a dummy service for the handler
        twilio = type('DummyTwilio', (), {})()

    # Initialize message handler
    handler = MessageHandler(series, twilio)

    # Initialize Kafka consumer
    consumer = KafkaMessageConsumer(config, handler)

    logger.info("=" * 50)
    logger.info("Series Hackathon Server Starting")
    logger.info("=" * 50)
    logger.info(f"Sender Number: {config.SERIES_SENDER_NUMBER}")
    logger.info(f"Kafka Topic: {config.KAFKA_TOPIC}")
    logger.info("=" * 50)
    logger.info(f"Text {config.SERIES_SENDER_NUMBER} to test!")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)

    try:
        consumer.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        consumer.close()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
