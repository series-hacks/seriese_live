# Series Hackathon Core Stack

Python backend integrating iMessage (Series API), Kafka (Confluent Cloud), and Twilio (conference calls).

## Team Brawl Stars
- Ali Bauyrzhan (+19297283369)
- Raiymbek Kokteubay (+17186030719)

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

The `.env` file is pre-configured with Series API and Kafka credentials.

For Twilio (optional), update these values:
```env
TWILIO_ACCOUNT_SID=<your_account_sid>
TWILIO_AUTH_TOKEN=<your_auth_token>
TWILIO_PHONE_NUMBER=<your_twilio_number>
```

### 3. Run the Server

```bash
python main.py
```

### 4. Test

Send an iMessage to `+16463029478`. You should receive an echo reply.

## Project Structure

```
series/
├── main.py                   # Entry point
├── config.py                 # Environment loader
├── consumers/
│   └── kafka_consumer.py     # Kafka consumer (SASL_SSL)
├── services/
│   ├── series_api.py         # iMessage API client
│   └── twilio_service.py     # Conference call service
├── handlers/
│   └── message_handler.py    # Event routing
├── .env                      # Credentials
└── requirements.txt          # Dependencies
```

## API Reference

### Series API (iMessage)

```python
from services.series_api import SeriesAPI
from config import Config

config = Config()
series = SeriesAPI(
    config.SERIES_API_KEY,
    config.SERIES_BASE_URL,
    config.SERIES_SENDER_NUMBER
)

# Create new chat and send message
chat = series.create_chat(["+1234567890"], "Hello!")

# Send to existing chat
series.send_message(chat_id=123, text="Follow up message")

# Reactions
series.add_reaction(message_id=456, reaction_type="love")

# Typing indicators
series.start_typing(chat_id=123)
series.stop_typing(chat_id=123)

# Check iMessage availability
result = series.check_imessage_availability("+1234567890")
```

### Twilio Conferences

```python
from services.twilio_service import TwilioService
from config import Config

config = Config()
twilio = TwilioService(
    config.TWILIO_ACCOUNT_SID,
    config.TWILIO_AUTH_TOKEN,
    config.TWILIO_PHONE_NUMBER
)

# Create conference and add participants
conf_name = twilio.create_conference("my-conference")
call_sid = twilio.add_participant(conf_name, "+19297283369")

# Get conference details
conf = twilio.get_conference_by_name(conf_name)

# Manage participants
twilio.mute_participant(conf['sid'], call_sid)
twilio.unmute_participant(conf['sid'], call_sid)
twilio.remove_participant(conf['sid'], call_sid)

# List conferences
active = twilio.list_conferences(status="in-progress")

# End conference
twilio.end_conference(conf['sid'])
```

## Kafka Events

The consumer handles these event types:

| Event Type | Description |
|------------|-------------|
| `message.received` | Incoming iMessage |
| `typing_indicator.received` | User started typing |
| `typing_indicator.removed` | User stopped typing |

### Event Structure

```json
{
  "api_version": "v2",
  "event_type": "message.received",
  "data": {
    "chat_id": "1698665",
    "from_phone": "+19176256109",
    "text": "Hello!",
    "id": "53077912",
    "sent_at": "2025-12-05 14:42:05 -0600"
  }
}
```

## Adding AI Integration

The `MessageHandler.handle_message()` method is the integration point for AI:

```python
def handle_message(self, data: dict):
    from_phone = data.get('from_phone')
    text = data.get('text', '')
    chat_id = data.get('chat_id')

    # TODO: Replace with AI processing
    # response = ai_agent.process(text)
    response = f"Got your message: {text}"

    self.series.send_message(int(chat_id), response)
```

## Twilio Setup

1. Create account at [twilio.com](https://www.twilio.com)
2. Get Account SID and Auth Token from Console
3. Buy a phone number with Voice capability
4. Update `.env` with credentials

## Troubleshooting

### Kafka Connection Issues
- Verify Confluent Cloud credentials
- Check network connectivity to `pkc-619z3.us-east1.gcp.confluent.cloud:9092`

### iMessage Not Sending
- Ensure recipient has iMessage enabled
- Check Series API key is valid
- Verify phone number is E.164 format (+1XXXXXXXXXX)

### Twilio Calls Not Working
- Verify account has sufficient balance
- Check phone number has Voice capability
- Ensure TwiML is valid XML
