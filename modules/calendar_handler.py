import datetime
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from utils.logger import logger
import uuid
import re 

class CalendarHandler:
    def __init__(self, credentials):
        """Initializes the CalendarHandler with Google Calendar API service."""
        try:
            self.service = build('calendar', 'v3', credentials=credentials)
            logger.info("Google Calendar service initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar service: {e}", exc_info=True)
            self.service = None
            
    def _get_direct_download_link(self, drive_url):
        """Converts a Google Drive view URL to a direct download link."""
        if not drive_url:
            return None
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', drive_url)
        if match:
            file_id = match.group(1)
            return f'https://drive.google.com/uc?export=download&id={file_id}'
        return drive_url
        
    def find_available_slots(self, interviewer_email, duration_minutes, days_to_check=7):
        """
        Finds available time slots for an interviewer by fetching ALL events and treating them as busy.
        """
        if not self.service:
            logger.error("Calendar service is not available.")
            return []

        local_tz = ZoneInfo("Asia/Kolkata")
        now = datetime.datetime.now(local_tz)
        potential_slot_start = now      
        if potential_slot_start.hour >= 18:
            potential_slot_start = (potential_slot_start + datetime.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
  
        if potential_slot_start.hour < 9:
            potential_slot_start = potential_slot_start.replace(hour=9, minute=0, second=0, microsecond=0)
        if potential_slot_start.minute % 15 != 0:
            minutes_to_add = 15 - (potential_slot_start.minute % 15)
            potential_slot_start += datetime.timedelta(minutes=minutes_to_add)
        potential_slot_start = potential_slot_start.replace(second=0, microsecond=0)

        time_max = potential_slot_start + datetime.timedelta(days=days_to_check)
        logger.info(f"Searching for free slots for {interviewer_email} from {potential_slot_start} to {time_max}")

        try:
            events_result = self.service.events().list(
                calendarId=interviewer_email,
                timeMin=potential_slot_start.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            busy_slots_raw = events_result.get('items', [])
            logger.info(f"Found {len(busy_slots_raw)} total events on the calendar.")

        except Exception as e:
            logger.error(f"Failed to fetch calendar events for {interviewer_email}: {e}")
            return []
        
        busy_slots = []
        for event in busy_slots_raw:
            start_info = event.get('start', {}); end_info = event.get('end', {})
            start_str = start_info.get('dateTime', start_info.get('date')); end_str = end_info.get('dateTime', end_info.get('date'))
            if not start_str or not end_str: continue

            if 'T' not in start_str:
                busy_start = datetime.datetime.fromisoformat(start_str).replace(tzinfo=local_tz)
                busy_end = datetime.datetime.fromisoformat(end_str).replace(tzinfo=local_tz)
            else:
                busy_start = datetime.datetime.fromisoformat(start_str); busy_end = datetime.datetime.fromisoformat(end_str)
            busy_slots.append({'start': busy_start, 'end': busy_end})

        available_slots = []
        while potential_slot_start < time_max:
            # Skip weekends robustly
            if potential_slot_start.weekday() >= 5: # 5 = Saturday, 6 = Sunday
                days_to_add = 7 - potential_slot_start.weekday()
                potential_slot_start = (potential_slot_start + datetime.timedelta(days=days_to_add)).replace(hour=9, minute=0)
                continue
            
            # Reset to 9 AM on the next day if we go past 6 PM
            if potential_slot_start.hour >= 18:
                potential_slot_start = (potential_slot_start + datetime.timedelta(days=1)).replace(hour=9, minute=0)
                continue

            potential_slot_end = potential_slot_start + datetime.timedelta(minutes=duration_minutes)
            
            is_free = True
            for busy_period in busy_slots:
                if potential_slot_start < busy_period['end'] and potential_slot_end > busy_period['start']:
                    is_free = False
                    break
            
            if is_free:
                available_slots.append(potential_slot_start)

            potential_slot_start += datetime.timedelta(minutes=15)

        logger.info(f"Found {len(available_slots)} available slots for {interviewer_email}.")
        return available_slots

    def create_calendar_event(self, applicant_name, applicant_email, interviewer_email, start_time, end_time, event_summary, description, resume_url=None, jd_info=None):
        if not self.service:
            logger.error("Calendar service is not available.")
            return None

        attachments = []
        # Use the helper method to convert the URLs
        if resume_url:
            direct_resume_url = self._get_direct_download_link(resume_url)
            if direct_resume_url:
                attachments.append({
                    'fileUrl': direct_resume_url,
                    'title': f"Resume - {applicant_name}"
                })

        if jd_info and jd_info.get('drive_url'):
            direct_jd_url = self._get_direct_download_link(jd_info['drive_url'])
            if direct_jd_url:
                attachments.append({
                    'fileUrl': direct_jd_url,
                    'title': f"Job Description - {jd_info['name']}"
                })

        event_body = {
            'summary': event_summary,
            'description': description,
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
            'attendees': [{'email': interviewer_email}, {'email': applicant_email}],
            'conferenceData': {'createRequest': {'requestId': f"{uuid.uuid4().hex}", 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}},
            'reminders': {'useDefault': True},
        }

        # The 'attachments' key should only be added if it's not empty
        if attachments:
            event_body['attachments'] = attachments
            logger.info(f"Attaching {len(attachments)} file(s) to the calendar event.")
        else:
            logger.warning("No valid attachment URLs found to add to the event.")

        try:
            logger.info(f"Creating calendar event for {applicant_name} with {interviewer_email}")
            created_event = self.service.events().insert(
                calendarId='primary', body=event_body, sendNotifications=True, conferenceDataVersion=1
            ).execute()
            logger.info(f"Event created successfully. Event ID: {created_event['id']}")
            return created_event
        except Exception as e:
            logger.error(f"Failed to create calendar event: {e}", exc_info=True)
            logger.debug(f"Event body that failed: {event_body}")
            return None

