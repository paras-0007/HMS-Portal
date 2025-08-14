import base64
import email
import re
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from utils.logger import logger
from utils.file_utils import create_temp_file
from typing import List, Dict


class EmailHandler:
    def __init__(self, credentials): 
        """Initializes the EmailHandler with user-specific credentials."""
        try:
            self.service = build('gmail', 'v1', credentials=credentials)
            logger.info("Gmail service initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service: {e}", exc_info=True)
            self.service = None

    def fetch_unread_emails(self):
        """Fetch unread emails that are likely job applications."""
        try:
            keywords = ['"job application"', '"applying for"', 'resume', 'cv']
            keyword_query = "{" + " OR ".join(keywords) + "}"
            query = f'is:unread has:attachment {{filename:pdf OR filename:docx}} {keyword_query}'
            
            result = self.service.users().messages().list(userId='me', q=query).execute()
            return result.get('messages', [])
        except Exception as e:
            logger.error(f"Email fetch failed: {str(e)}", exc_info=True)
            return []

    def fetch_new_messages_in_thread(self, thread_id):
        """Fetches all messages in a specific thread."""
        try:
            thread = self.service.users().threads().get(userId='me', id=thread_id).execute()
            return thread.get('messages', [])
        except Exception as e:
            logger.error(f"Could not fetch thread {thread_id}: {e}")
            return []

    def get_email_content(self, msg_id):
        """Extracts email content by parsing the 'payload' for maximum compatibility."""
        try:
            msg = self.service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            if not msg or 'payload' not in msg:
                logger.error(f"Could not retrieve a valid payload for email ID: {msg_id}. Skipping.")
                return None

            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = self._get_header(headers, 'Subject')
            sender = self._extract_email(self._get_header(headers, 'From'))
            body = self._extract_body_from_payload(payload)

            return {
                'id': msg.get('id'),
                'thread_id': msg.get('threadId'),
                'subject': subject,
                'sender': sender,
                'body': body
            }
        except Exception as e:
            logger.error(f"Email content extraction failed for {msg_id}: {str(e)}", exc_info=True)
            return None

    def _get_header(self, headers, name):
        """Gets a specific header value from a list of headers."""
        for header in headers:
            if header['name'].lower() == name.lower():
                return self._decode_header(header['value'])
        return ""

    def _extract_body_from_payload(self, payload):
        """Recursively extracts the plain text body from the message payload."""
        body = ""
        if payload.get('mimeType') == 'text/plain':
            data = payload.get('body', {}).get('data')
            if data:
                try:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                except Exception:
                    return ""
        
        if 'parts' in payload:
            for part in payload['parts']:
                body += self._extract_body_from_payload(part)
        return body

    def send_email(self, to: List[str], subject: str, body: str, attachments: List[Dict] = None):
        """
        Sends an email using the Gmail API, with optional attachments.
        'to' is a list of email addresses.
        'attachments' is a list of dicts, e.g., [{'content': data, 'filename': 'file.pdf', 'maintype': 'application', 'subtype': 'octet-stream'}]
        """
        try:
            message = MIMEMultipart()
            message['to'] = ", ".join(to) # Join multiple recipients
            message['subject'] = subject

            message.attach(MIMEText(body, 'html'))

            if attachments:
                for attachment in attachments:
                    part = MIMEBase(attachment.get('maintype', 'application'), attachment.get('subtype', 'octet-stream'))
                    part.set_payload(attachment['content'])
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{attachment["filename"]}"')
                    message.attach(part)
                    logger.info(f"Attaching file: {attachment['filename']}")

            create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
            
            sent_message = self.service.users().messages().send(userId='me', body=create_message).execute()
            
            logger.info(f"Email sent successfully to {', '.join(to)}. Message ID: {sent_message['id']}")
            return sent_message
        except HttpError as error:
            logger.error(f"An error occurred while sending email: {error}")
            return None
        except Exception as e:
            logger.error(f"A general error occurred in send_email: {e}", exc_info=True)
            return None

    def save_attachment(self, msg_id):
        """Saves PDF or DOCX attachment to a temp file."""
        try:
            msg = self.service.users().messages().get(userId='me', id=msg_id).execute()
            parts = msg['payload'].get('parts', [])
            for part in parts:
                filename = part.get('filename', '')
                if filename and (filename.lower().endswith('.pdf') or filename.lower().endswith('.docx')):
                    body = part.get('body', {})
                    att_id = body.get('attachmentId')
                    if att_id:
                        att = self.service.users().messages().attachments().get(userId='me', messageId=msg_id, id=att_id).execute()
                        file_data = base64.urlsafe_b64decode(att['data'])
                        file_path = create_temp_file(filename)
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                        return file_path
            return None
        except Exception as e:
            logger.error(f"Attachment save failed for {msg_id}: {str(e)}", exc_info=True)
            return None

    def mark_as_read(self, msg_id):
        """Marks an email as read."""
        try:
            self.service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
            return True
        except Exception as e:
            logger.error(f"Mark as read failed for {msg_id}: {str(e)}", exc_info=True)
            return False

    def _decode_header(self, header):
        """Decodes email headers."""
        if header is None: return ""
        decoded = decode_header(header)
        return ''.join([t[0].decode(t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0] for t in decoded])

    def _extract_email(self, header):
        """Extracts email address from a header string."""
        match = re.search(r'<([^>]+)>', header)

        return match.group(1) if match else header




# import base64
# import email
# import re
# from email.header import decode_header
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from email.mime.base import MIMEBase
# from email import encoders
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError
# from utils.logger import logger
# from utils.file_utils import create_temp_file


# class EmailHandler:
#     def __init__(self, credentials): 
#         """Initializes the EmailHandler with user-specific credentials."""
#         try:
#             self.service = build('gmail', 'v1', credentials=credentials)
#             logger.info("Gmail service initialized successfully.")
#         except Exception as e:
#             logger.error(f"Failed to initialize Gmail service: {e}", exc_info=True)
#             self.service = None

#     def fetch_unread_emails(self):
#         """Fetch unread emails that are likely job applications."""
#         try:
#             keywords = ['"job application"', '"applying for"', 'resume', 'cv']
#             keyword_query = "{" + " OR ".join(keywords) + "}"
#             query = f'is:unread has:attachment {{filename:pdf OR filename:docx}} {keyword_query}'
            
#             result = self.service.users().messages().list(userId='me', q=query).execute()
#             return result.get('messages', [])
#         except Exception as e:
#             logger.error(f"Email fetch failed: {str(e)}", exc_info=True)
#             return []

#     def fetch_new_messages_in_thread(self, thread_id):
#         """Fetches all messages in a specific thread."""
#         try:
#             thread = self.service.users().threads().get(userId='me', id=thread_id).execute()
#             return thread.get('messages', [])
#         except Exception as e:
#             logger.error(f"Could not fetch thread {thread_id}: {e}")
#             return []

#     def get_email_content(self, msg_id):
#         """Extracts email content by parsing the 'payload' for maximum compatibility."""
#         try:
#             msg = self.service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
#             if not msg or 'payload' not in msg:
#                 logger.error(f"Could not retrieve a valid payload for email ID: {msg_id}. Skipping.")
#                 return None

#             payload = msg.get('payload', {})
#             headers = payload.get('headers', [])
            
#             subject = self._get_header(headers, 'Subject')
#             sender = self._extract_email(self._get_header(headers, 'From'))
#             body = self._extract_body_from_payload(payload)

#             return {
#                 'id': msg.get('id'),
#                 'thread_id': msg.get('threadId'),
#                 'subject': subject,
#                 'sender': sender,
#                 'body': body
#             }
#         except Exception as e:
#             logger.error(f"Email content extraction failed for {msg_id}: {str(e)}", exc_info=True)
#             return None

#     def _get_header(self, headers, name):
#         """Gets a specific header value from a list of headers."""
#         for header in headers:
#             if header['name'].lower() == name.lower():
#                 return self._decode_header(header['value'])
#         return ""

#     def _extract_body_from_payload(self, payload):
#         """Recursively extracts the plain text body from the message payload."""
#         body = ""
#         if payload.get('mimeType') == 'text/plain':
#             data = payload.get('body', {}).get('data')
#             if data:
#                 try:
#                     return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
#                 except Exception:
#                     return ""
        
#         if 'parts' in payload:
#             for part in payload['parts']:
#                 body += self._extract_body_from_payload(part)
#         return body

#     def send_email(self, to, subject, body, thread_id=None, attachment=None):
#         """Sends an email using the Gmail API, with optional attachment."""
#         try:
#             message = MIMEMultipart()
#             message['to'] = to
#             message['subject'] = subject

#             # Attach the email body
#             message.attach(MIMEText(body, 'html'))

#             # Attach the file, if provided
#             if attachment:
#                 part = MIMEBase('application', 'octet-stream')
#                 part.set_payload(attachment.getvalue())
#                 encoders.encode_base64(part)
#                 part.add_header(
#                     'Content-Disposition',
#                     f'attachment; filename="{attachment.name}"',
#                 )
#                 message.attach(part)
#                 logger.info(f"Attaching file: {attachment.name}")

#             # Prepare the message for the API
#             create_message = {
#                 'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()
#             }
            
#             if thread_id:
#                 create_message['threadId'] = thread_id

#             sent_message = self.service.users().messages().send(
#                 userId='me', body=create_message
#             ).execute()
            
#             logger.info(f"Email sent successfully to {to}. Message ID: {sent_message['id']}")
#             return sent_message
#         except HttpError as error:
#             logger.error(f"An error occurred while sending email: {error}")
#             return None
#         except Exception as e:
#             logger.error(f"A general error occurred in send_email: {e}", exc_info=True)
#             return None

#     def save_attachment(self, msg_id):
#         """Saves PDF or DOCX attachment to a temp file."""
#         try:
#             msg = self.service.users().messages().get(userId='me', id=msg_id).execute()
#             parts = msg['payload'].get('parts', [])
#             for part in parts:
#                 filename = part.get('filename', '')
#                 if filename and (filename.lower().endswith('.pdf') or filename.lower().endswith('.docx')):
#                     body = part.get('body', {})
#                     att_id = body.get('attachmentId')
#                     if att_id:
#                         att = self.service.users().messages().attachments().get(userId='me', messageId=msg_id, id=att_id).execute()
#                         file_data = base64.urlsafe_b64decode(att['data'])
#                         file_path = create_temp_file(filename)
#                         with open(file_path, 'wb') as f:
#                             f.write(file_data)
#                         return file_path
#             return None
#         except Exception as e:
#             logger.error(f"Attachment save failed for {msg_id}: {str(e)}", exc_info=True)
#             return None

#     def mark_as_read(self, msg_id):
#         """Marks an email as read."""
#         try:
#             self.service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
#             return True
#         except Exception as e:
#             logger.error(f"Mark as read failed for {msg_id}: {str(e)}", exc_info=True)
#             return False

#     def _decode_header(self, header):
#         """Decodes email headers."""
#         if header is None: return ""
#         decoded = decode_header(header)
#         return ''.join([t[0].decode(t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0] for t in decoded])

#     def _extract_email(self, header):
#         """Extracts email address from a header string."""
#         match = re.search(r'<([^>]+)>', header)

#         return match.group(1) if match else header

