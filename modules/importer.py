import pandas as pd
from urllib.parse import urlparse
import requests
import io
import os
import re
import uuid

from modules.database_handler import DatabaseHandler
from modules.ai_classifier import AIClassifier
from modules.pdf_processor import FileProcessor
from modules.drive_handler import DriveHandler
from utils.logger import logger

class Importer:
    def __init__(self, credentials):
        self.credentials = credentials
        self.db_handler = DatabaseHandler()
        self.ai_classifier = AIClassifier()
        self.file_processor = FileProcessor()
        self.drive_handler = DriveHandler(credentials)

    def _get_gdrive_download_url(self, url):
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return f'https://drive.google.com/uc?export=download&id={match.group(1)}'
        return url

    def _download_file(self, url):
        try:
            download_url = self._get_gdrive_download_url(url)
            session = requests.Session()
            response = session.get(download_url, stream=True)
            response.raise_for_status()
            
            content_disposition = response.headers.get('content-disposition')
            filename = f"{uuid.uuid4()}.tmp" # Default filename
            if content_disposition:
                filenames = re.findall('filename="(.+)"', content_disposition)
                if filenames: filename = filenames[0]

            temp_file_path = f"/tmp/{os.path.basename(filename).replace(' ', '_')}"
            with open(temp_file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
            logger.info(f"Successfully downloaded file to {temp_file_path}")
            return temp_file_path
        except Exception as e:
            logger.error(f"Failed to download file from {url}: {e}", exc_info=True)
            return None

    def _normalize_columns(self, df):
        """Normalizes dataframe columns to a consistent format."""
        cols = {col: col.strip().lower().replace(' ', '_').replace('-', '_') for col in df.columns}
        df = df.rename(columns=cols)
        
        # Define potential aliases for our target fields
        rename_map = {
            'cv_url': ['cv_url', 'cvurl', 'cv_link', 'resume_url', 'resume_link'],
            'job_history': ['job_history', 'jobhistory', 'work_experience'],
            'name': ['name', 'full_name'],
            'email': ['email', 'email_address'],
            'phone': ['phone', 'phone_number', 'mobile']
        }

        # Reverse map for finding the right column in the df
        final_cols = {}
        for target, aliases in rename_map.items():
            for alias in aliases:
                if alias in df.columns:
                    final_cols[alias] = target
                    break # Found the first matching alias
        
        df = df.rename(columns=final_cols)
        return df

    def import_from_local_resume_file(self, uploaded_file):
        """Processes a single, locally uploaded resume file."""
        temp_file_path = None
        try:
            temp_dir = "/tmp"
            os.makedirs(temp_dir, exist_ok=True)
            temp_file_path = os.path.join(temp_dir, uploaded_file.name)
            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            logger.info(f"Temporarily saved uploaded resume to {temp_file_path}")

            resume_text = self.file_processor.extract_text(temp_file_path)
            if not resume_text:
                logger.error(f"Could not extract text from local resume: {uploaded_file.name}")
                return None, "Could not extract text from the resume."

            ai_data = self.ai_classifier.extract_info("", "", resume_text)
            
            drive_url = self.drive_handler.upload_to_drive(temp_file_path)
            if not drive_url:
                logger.error(f"Failed to upload resume to Google Drive: {uploaded_file.name}")
                return None, "Failed to upload the resume to cloud storage."

            applicant_data = {
                'Name': ai_data.get('Name'), 'Email': ai_data.get('Email'),
                'Phone': ai_data.get('Phone'), 'Education': ai_data.get('Education'),
                'JobHistory': ai_data.get('JobHistory'), 'Domain': ai_data.get('Domain', 'Other'),
                'CV_URL': drive_url, 'Status': 'New'
            }
            
            applicant_id = self.db_handler.insert_applicant_and_communication(applicant_data, {})
            if applicant_id:
                return applicant_id, f"Successfully imported applicant: {ai_data.get('Name')}"
            else:
                return None, f"Failed to import applicant. They may already exist with email: {ai_data.get('Email')}"

        except Exception as e:
            logger.error(f"Error importing local resume file: {e}", exc_info=True)
            return None, f"An unexpected error occurred during import: {e}"
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    def _process_dataframe(self, df):
        df = self._normalize_columns(df)
        inserted_count, skipped_count = 0, 0

        for _, row in df.iterrows():
            applicant_data = row.to_dict()
            temp_file_path = None
            
            try:
                if pd.isna(row.get('job_history')) and 'cv_url' in df.columns and pd.notna(row.get('cv_url')):
                    temp_file_path = self._download_file(row['cv_url'])
                    if temp_file_path:
                        drive_url = self.drive_handler.upload_to_drive(temp_file_path)
                        applicant_data['CV_URL'] = drive_url
                        
                        resume_text = self.file_processor.extract_text(temp_file_path)
                        ai_data = self.ai_classifier.extract_info("", "", resume_text)
                        
                        for key, value in ai_data.items():
                            db_key = key.lower()
                            if db_key in ['name', 'phone', 'education', 'jobhistory']:
                                db_key = 'job_history' if db_key == 'jobhistory' else db_key
                                applicant_data[db_key.title()] = applicant_data.get(db_key.title()) or value

                db_insert_data = {
                    "Name": applicant_data.get('name'),
                    "Email": applicant_data.get('email'),
                    "Phone": applicant_data.get('phone'),
                    "Domain": applicant_data.get('domain', 'Other'),
                    "Education": applicant_data.get('education'),
                    "JobHistory": applicant_data.get('job_history'),
                    "CV_URL": applicant_data.get('cv_url'),
                }
                
                if self.db_handler.insert_applicant_and_communication(db_insert_data, {}):
                    inserted_count += 1
                else:
                    skipped_count += 1
            
            except Exception as e:
                logger.error(f"Error processing row for {row.get('email', 'N/A')}: {e}", exc_info=True)
                skipped_count += 1
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
        
        return inserted_count, skipped_count
