from utils.logger import logger
from modules.email_handler import EmailHandler
from modules.drive_handler import DriveHandler
from modules.pdf_processor import FileProcessor
from modules.ai_classifier import AIClassifier
from modules.database_handler import DatabaseHandler

class ProcessingEngine:
    def __init__(self, credentials):
        self.credentials = credentials
        # Handlers are initialized here with the user's credentials
        self.email_handler = EmailHandler(credentials)
        self.drive_handler = DriveHandler(credentials)
        self.file_processor = FileProcessor()
        self.ai_classifier = AIClassifier()
        self.db_handler = DatabaseHandler()
        # Use a set to track processed messages within this run
        self.processed_message_ids_this_run = set()

    def run_once(self):
        """
        Runs one full cycle of processing new applications and replies.
        Returns a summary of the actions taken.
        """
        logger.info("Starting a single run of the processing engine.")
        self.db_handler.create_tables() # Ensure tables exist
        
        new_apps = self._process_new_applications()
        new_replies = self._process_replies()

        summary = f"Processing complete. Found {new_apps} new application(s) and {new_replies} new reply/replies."
        logger.info(summary)
        return summary

    def _process_new_applications(self):
        logger.info("Checking for new applications...")
        messages = self.email_handler.fetch_unread_emails()
        if not messages:
            logger.info("No new applications found.")
            return 0
        
        count = 0
        for msg in messages:
            if msg['id'] in self.processed_message_ids_this_run:
                continue
            
            self._process_single_email(msg['id'])
            self.processed_message_ids_this_run.add(msg['id'])
            count += 1
        return count

    def _process_replies(self):
        logger.info("Checking for replies in active threads...")
        active_threads = self.db_handler.get_active_threads()
        count = 0

        for applicant_id, thread_id in active_threads:
            try:
                messages_in_thread = self.email_handler.fetch_new_messages_in_thread(thread_id)
            except HttpError as e:
                if e.resp.status == 404:
                    logger.warning(f"Thread ID {thread_id} for applicant {applicant_id} not found (404). Setting it to NULL in the database to prevent future errors.")
                    self.db_handler.update_applicant_thread_id(applicant_id, None)
                else:
                    logger.error(f"An HTTP error occurred for thread {thread_id}: {e}")
                continue
            except Exception as e:
                logger.error(f"A general error occurred while processing thread {thread_id}: {e}")
                continue
            
            if not messages_in_thread:
                continue
            
            convos = self.db_handler.get_conversations(applicant_id)
            known_ids = set(convos['gmail_message_id'].tolist()) if not convos.empty else set()

            for msg_summary in messages_in_thread:
                msg_id = msg_summary['id']
                if msg_id in known_ids or msg_id in self.processed_message_ids_this_run:
                    continue

                email_data = self.email_handler.get_email_content(msg_id)
                if not email_data or email_data['sender'] == 'me': # Skip our own emails
                    self.processed_message_ids_this_run.add(msg_id)
                    continue
                
                comm_data = {
                    "applicant_id": applicant_id, "gmail_message_id": email_data['id'],
                    "sender": email_data['sender'], "subject": email_data['subject'],
                    "body": email_data['body'], "direction": "Incoming"
                }
                
                self.db_handler.insert_communication(comm_data)
                self.processed_message_ids_this_run.add(msg_id)
                count += 1
                logger.info(f"New reply from applicant {applicant_id} (message: {msg_id}) has been saved.")
        return count

    def _process_single_email(self, msg_id):
        logger.info(f"Processing new application with email ID: {msg_id}")
        try:
            email_data = self.email_handler.get_email_content(msg_id)
            if not email_data: return

            file_path = self.email_handler.save_attachment(msg_id)
            if not file_path:
                logger.warning(f"No processable attachment in email {msg_id}. Skipping.")
                self.email_handler.mark_as_read(msg_id)
                return

            drive_url = self.drive_handler.upload_to_drive(file_path)
            resume_text = self.file_processor.extract_text(file_path)

            ai_data = self.ai_classifier.extract_info(email_data['subject'], email_data['body'], resume_text)
            if not ai_data or not ai_data.get('Name'):
                logger.error(f"AI processing failed to extract essential data for email {msg_id}. The email will remain unread and will be retried in the next cycle.")
                return
            applicant_data = {**ai_data, 'Email': email_data['sender'], 'CV_URL': drive_url}
            
            applicant_data = {**ai_data, 'Email': email_data['sender'], 'CV_URL': drive_url}
            
            applicant_id = self.db_handler.insert_applicant_and_communication(applicant_data, email_data)
            
            if applicant_id:
                self.email_handler.mark_as_read(msg_id)
            else:
                logger.warning(f"Applicant creation failed for email {msg_id}, likely a duplicate. Marking as read.")
                self.email_handler.mark_as_read(msg_id)
        except Exception as e:
            logger.error(f"Failed to process email {msg_id}: {str(e)}", exc_info=True)
