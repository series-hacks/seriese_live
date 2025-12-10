# Series Live

Voice AI-powered Omegle for iMessages. Series Live connects users through group calls, introduces participants with AI-generated intros, and keeps conversations flowing by participating during awkward pauses.

## What It Does

- **Smart Matchmaking**: Text your interests and get matched with compatible people
- **AI Introductions**: When a call starts, AI introduces each participant based on their profiles
- **Conversation Flow**: AI participates during awkward silences to keep discussions engaging
- **iMessage Integration**: Everything happens through iMessage - no app download required

## How It Works

1. **Join the Waitroom**: Send "Call" to enter the matchmaking queue
2. **Get Matched**: Based on interests, you'll be matched with others
3. **Confirm**: Review the match profile and reply "Yes" to connect
4. **Get Called**: Twilio calls both participants into a conference
5. **AI Hosts**: Voice AI introduces participants and keeps conversation flowing

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file with:

```env
# Series API (iMessage)
SERIES_API_KEY=<your_api_key>
SERIES_BASE_URL=<api_base_url>
SERIES_SENDER_NUMBER=<sender_number>

# Twilio (Voice Calls)
TWILIO_ACCOUNT_SID=<your_account_sid>
TWILIO_AUTH_TOKEN=<your_auth_token>
TWILIO_PHONE_NUMBER=<your_twilio_number>

# OpenAI (AI Features)
OPENAI_API_KEY=<your_openai_key>

# User Profiles (for demo)
USER1_PHONE=<phone1>
USER1_NAME=<name1>
USER2_PHONE=<phone2>
USER2_NAME=<name2>

# Webhook (for ngrok)
NGROK_URL=<your_ngrok_url>
```

### 3. Run the Server

```bash
python main.py
```

### 4. Start a Conversation

Send any of these commands via iMessage:
- **Call** - Enter the waitroom to find a match
- **Leave** - Exit the waitroom
- **Status** - Check your waitroom status
- **List** - See who's waiting
- **Summary** - Get AI summary of your last call
- **Help** - Show available commands

## Project Structure

```
series/
├── main.py                   # Entry point
├── config.py                 # Environment loader
├── consumers/
│   └── kafka_consumer.py     # Kafka consumer for iMessage events
├── services/
│   ├── series_api.py         # iMessage API client
│   ├── twilio_service.py     # Conference call service
│   ├── matchmaking.py        # Interest-based matching
│   └── notetaker.py          # Call transcription & summary
├── handlers/
│   └── message_handler.py    # Command & event routing
└── requirements.txt          # Dependencies
```

## Architecture

```
iMessage → Kafka → Message Handler → Matchmaking
                                   → Twilio Calls
                                   → AI Voice (Intro/Icebreakers)
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `Call` | Join the matchmaking waitroom |
| `Leave` | Exit the waitroom |
| `Status` | Check if you're in the waitroom |
| `List` | See who else is waiting |
| `Summary` | Get AI summary of your last call |
| `Help` | Show available commands |
| `Yes` | Accept a match |
| `No` | Decline a match |

## License

MIT
