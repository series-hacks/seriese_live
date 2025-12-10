import os
from dotenv import load_dotenv


class Config:
    def __init__(self):
        load_dotenv()

        # Series API
        self.SERIES_API_KEY = os.getenv('SERIES_API_KEY')
        self.SERIES_BASE_URL = os.getenv('SERIES_BASE_URL')
        self.SERIES_SENDER_NUMBER = os.getenv('SERIES_SENDER_NUMBER')

        # Kafka
        self.KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS')
        self.KAFKA_TOPIC = os.getenv('KAFKA_TOPIC')
        self.KAFKA_GROUP_ID = os.getenv('KAFKA_GROUP_ID')
        self.KAFKA_CLIENT_ID = os.getenv('KAFKA_CLIENT_ID')
        self.KAFKA_SASL_USERNAME = os.getenv('KAFKA_SASL_USERNAME')
        self.KAFKA_SASL_PASSWORD = os.getenv('KAFKA_SASL_PASSWORD')

        # Twilio
        self.TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
        self.TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
        self.TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

    def validate(self) -> list[str]:
        """Validate required configuration. Returns list of missing fields."""
        missing = []

        # Required for Series API
        if not self.SERIES_API_KEY:
            missing.append('SERIES_API_KEY')
        if not self.SERIES_BASE_URL:
            missing.append('SERIES_BASE_URL')
        if not self.SERIES_SENDER_NUMBER:
            missing.append('SERIES_SENDER_NUMBER')

        # Required for Kafka
        if not self.KAFKA_BOOTSTRAP_SERVERS:
            missing.append('KAFKA_BOOTSTRAP_SERVERS')
        if not self.KAFKA_TOPIC:
            missing.append('KAFKA_TOPIC')
        if not self.KAFKA_GROUP_ID:
            missing.append('KAFKA_GROUP_ID')
        if not self.KAFKA_SASL_USERNAME:
            missing.append('KAFKA_SASL_USERNAME')
        if not self.KAFKA_SASL_PASSWORD:
            missing.append('KAFKA_SASL_PASSWORD')

        return missing

    def is_twilio_configured(self) -> bool:
        """Check if Twilio credentials are properly configured."""
        return (
            self.TWILIO_ACCOUNT_SID
            and self.TWILIO_AUTH_TOKEN
            and self.TWILIO_PHONE_NUMBER
            and not self.TWILIO_ACCOUNT_SID.startswith('<')
            and not self.TWILIO_AUTH_TOKEN.startswith('<')
            and not self.TWILIO_PHONE_NUMBER.startswith('<')
        )
