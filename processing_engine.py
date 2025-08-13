from utils.logger import logger
from modules.email_handler import EmailHandler
from modules.drive_handler import DriveHandler
from modules.pdf_processor import FileProcessor
from modules.ai_classifier import AIClassifier
from modules.database_handler import DatabaseHandler
from googleapiclient.errors import HttpError

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
        This is kept for any non-interactive script use, but the UI now uses granular methods.
        Returns a summary of the actions taken.
        """
        logger.info("Starting a single run of the processing engine.")
        self.db_handler.create_tables() # Ensure tables exist
        
        api_stats = self.ai_classifier.get_api_pool_status()
        logger.info(f"API Key Pool Status: {api_stats}")
        
        new_apps, failed_classifications = self.process_new_applications()
        new_replies = self.process_replies()

        final_api_stats = self.ai_classifier.get_api_pool_status()
        logger.info(f"Final API Key Pool Status: {final_api_stats}")

        summary = (f"Processing complete. Successfully processed {new_apps} new application(s), "
                  f"{failed_classifications} failed classifications, and {new_replies} new reply/replies.")
        
        if failed_classifications > 0:
            summary += f" Warning: {failed_classifications} applications could not be processed due to classification failures."
        
        logger.info(summary)
        return summary

    def process_new_applications(self):
        """UI-driven method to process all new application emails."""
        logger.info("Checking for new applications...")
        messages = self.email_handler.fetch_unread_emails()
        if not messages:
            logger.info("No new applications found.")
            return 0, 0
        
        successful_count = 0
        failed_count = 0
        
        for msg in messages:
            if msg['id'] in self.processed_message_ids_this_run:
                continue
            
            success = self.process_single_email(msg['id'])
            self.processed_message_ids_this_run.add(msg['id'])
            
            if success:
                successful_count += 1
            else:
                failed_count += 1
        
        return successful_count, failed_count

    def process_replies(self):
        """UI-driven method to process all replies in active threads."""
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

    def process_single_email(self, msg_id) -> bool:
        """
        Process a single email. Renamed to be public for UI orchestration.
        Returns True if successful, False if failed.
        """
        logger.info(f"Processing new application with email ID: {msg_id}")
        try:
            email_data = self.email_handler.get_email_content(msg_id)
            if not email_data: 
                return False

            file_path = self.email_handler.save_attachment(msg_id)
            if not file_path:
                logger.warning(f"No processable attachment in email {msg_id}. Skipping.")
                self.email_handler.mark_as_read(msg_id)
                return False

            drive_url = self.drive_handler.upload_to_drive(file_path)
            resume_text = self.file_processor.extract_text(file_path)

            # Attempt AI classification - no fallback to rule-based
            ai_data = self.ai_classifier.extract_info(email_data['subject'], email_data['body'], resume_text)
            
            if not ai_data or not ai_data.get('Name'):
                logger.error(f"AI classification failed for email {msg_id}. Cannot process this application without successful classification.")
                
                # Log detailed error information
                api_stats = self.ai_classifier.get_api_pool_status()
                logger.error(f"Current API Key Pool Status: {api_stats}")
                
                # Do NOT mark as read - leave unread for potential retry later
                # when API keys become available again
                logger.warning(f"Email {msg_id} will remain unread and will be retried in the next cycle when API keys are available.")
                return False
            
            # If classification successful, proceed with database insertion
            applicant_data = {**ai_data, 'Email': email_data['sender'], 'CV_URL': drive_url}
            
            applicant_id = self.db_handler.insert_applicant_and_communication(applicant_data, email_data)
            
            if applicant_id:
                self.email_handler.mark_as_read(msg_id)
                logger.info(f"Successfully processed and saved applicant from email {msg_id} with ID: {applicant_id}")
                return True
            else:
                logger.warning(f"Applicant creation failed for email {msg_id}, likely a duplicate. Marking as read.")
                self.email_handler.mark_as_read(msg_id)
                return False
                
        except Exception as e:
            logger.error(f"Failed to process email {msg_id}: {str(e)}", exc_info=True)
            return False

    def get_classification_status(self):
        """Get current status of the classification system for monitoring."""
        return self.ai_classifier.get_api_pool_status()
