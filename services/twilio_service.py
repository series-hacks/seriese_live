import logging
from typing import Optional
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)


class TwilioService:
    """Service for managing Twilio conference calls."""

    def __init__(self, account_sid: str, auth_token: str, phone_number: str):
        self.client = Client(account_sid, auth_token)
        self.phone_number = phone_number
        self.active_conferences = {}  # conference_name -> conference_sid

    def create_conference(self, conference_name: str) -> str:
        """
        Create a conference room.

        Note: Twilio conferences are created implicitly when the first
        participant joins. This method just returns the conference name
        for tracking purposes.

        Args:
            conference_name: Unique name for the conference

        Returns:
            Conference friendly name
        """
        logger.info(f"Conference '{conference_name}' ready for participants")
        return conference_name

    def add_participant(
        self,
        conference_name: str,
        phone_number: str,
        status_callback_url: Optional[str] = None
    ) -> str:
        """
        Call a phone number and add them to the conference.

        Args:
            conference_name: Name of the conference to join
            phone_number: E.164 formatted phone number to call
            status_callback_url: Optional webhook for call status updates

        Returns:
            Call SID
        """
        twiml = f'''
        <Response>
            <Dial>
                <Conference startConferenceOnEnter="true" endConferenceOnExit="false">
                    {conference_name}
                </Conference>
            </Dial>
        </Response>
        '''

        try:
            call_params = {
                'to': phone_number,
                'from_': self.phone_number,
                'twiml': twiml
            }

            if status_callback_url:
                call_params['status_callback'] = status_callback_url
                call_params['status_callback_event'] = ['initiated', 'ringing', 'answered', 'completed']

            call = self.client.calls.create(**call_params)

            logger.info(f"Called {phone_number} to join conference '{conference_name}' (Call SID: {call.sid})")
            return call.sid

        except TwilioRestException as e:
            logger.error(f"Failed to add participant {phone_number} to conference: {e}")
            raise

    def _get_conference_sid(self, conference_name: str) -> Optional[str]:
        """Get the SID of an active conference by name."""
        try:
            conferences = self.client.conferences.list(
                friendly_name=conference_name,
                status='in-progress'
            )
            if conferences:
                return conferences[0].sid
            return None
        except TwilioRestException as e:
            logger.error(f"Failed to get conference SID: {e}")
            return None

    def _get_participant_sid(self, conference_sid: str, call_sid: str) -> Optional[str]:
        """Get participant by call SID."""
        try:
            participant = self.client.conferences(conference_sid).participants(call_sid).fetch()
            return participant.call_sid
        except TwilioRestException:
            return None

    def mute_participant(self, conference_sid: str, call_sid: str) -> None:
        """
        Mute a participant in the conference.

        Args:
            conference_sid: Conference SID
            call_sid: Participant's call SID
        """
        try:
            self.client.conferences(conference_sid).participants(call_sid).update(muted=True)
            logger.info(f"Muted participant {call_sid} in conference {conference_sid}")
        except TwilioRestException as e:
            logger.error(f"Failed to mute participant: {e}")
            raise

    def unmute_participant(self, conference_sid: str, call_sid: str) -> None:
        """
        Unmute a participant in the conference.

        Args:
            conference_sid: Conference SID
            call_sid: Participant's call SID
        """
        try:
            self.client.conferences(conference_sid).participants(call_sid).update(muted=False)
            logger.info(f"Unmuted participant {call_sid} in conference {conference_sid}")
        except TwilioRestException as e:
            logger.error(f"Failed to unmute participant: {e}")
            raise

    def remove_participant(self, conference_sid: str, call_sid: str) -> None:
        """
        Remove a participant from the conference.

        Args:
            conference_sid: Conference SID
            call_sid: Participant's call SID
        """
        try:
            self.client.conferences(conference_sid).participants(call_sid).delete()
            logger.info(f"Removed participant {call_sid} from conference {conference_sid}")
        except TwilioRestException as e:
            logger.error(f"Failed to remove participant: {e}")
            raise

    def end_conference(self, conference_sid: str) -> None:
        """
        End conference and disconnect all participants.

        Args:
            conference_sid: Conference SID
        """
        try:
            self.client.conferences(conference_sid).update(status='completed')
            logger.info(f"Ended conference {conference_sid}")
        except TwilioRestException as e:
            logger.error(f"Failed to end conference: {e}")
            raise

    def list_conferences(self, status: str = "in-progress") -> list:
        """
        List conferences by status.

        Args:
            status: Conference status filter (in-progress, completed, etc.)

        Returns:
            List of conference objects
        """
        try:
            conferences = self.client.conferences.list(status=status)
            return [
                {
                    'sid': conf.sid,
                    'friendly_name': conf.friendly_name,
                    'status': conf.status,
                    'date_created': str(conf.date_created)
                }
                for conf in conferences
            ]
        except TwilioRestException as e:
            logger.error(f"Failed to list conferences: {e}")
            raise

    def get_participants(self, conference_sid: str) -> list:
        """
        List all participants in a conference.

        Args:
            conference_sid: Conference SID

        Returns:
            List of participant objects
        """
        try:
            participants = self.client.conferences(conference_sid).participants.list()
            return [
                {
                    'call_sid': p.call_sid,
                    'muted': p.muted,
                    'hold': p.hold,
                    'status': p.status
                }
                for p in participants
            ]
        except TwilioRestException as e:
            logger.error(f"Failed to get participants: {e}")
            raise

    def get_conference_by_name(self, conference_name: str) -> Optional[dict]:
        """
        Get conference details by friendly name.

        Args:
            conference_name: Conference friendly name

        Returns:
            Conference details or None if not found
        """
        try:
            conferences = self.client.conferences.list(
                friendly_name=conference_name,
                status='in-progress'
            )
            if conferences:
                conf = conferences[0]
                return {
                    'sid': conf.sid,
                    'friendly_name': conf.friendly_name,
                    'status': conf.status,
                    'date_created': str(conf.date_created)
                }
            return None
        except TwilioRestException as e:
            logger.error(f"Failed to get conference by name: {e}")
            return None
