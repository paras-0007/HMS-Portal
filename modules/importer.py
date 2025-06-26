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
from modules.drive_handler import DriveHandler  # Re-used for uploading extracted resumes
from utils.logger import logger

class Importer:
    """
    Handles various methods of importing applicant data into the system.
    """
    def __init__(self, credentials):
        self.db_handler = DatabaseHandler()
        self.ai_classifier = AIClassifier()
        self.file_processor = FileProcessor()
        self.drive_handler = DriveHandler(credentials)

    def _get_gdrive_download_url(self, url):
        """
        Converts a standard Google Drive file viewer URL to a direct download URL.
        """
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            file_id = match.group(1)
            return f'https://drive.google.com/uc?export=download&id={file_id}'
        return url # Return original URL if it's not a recognizable GDrive link

    def _download_file(self, url):
        """
        Downloads a file from a URL, handling Google Drive links, and saves it to a temporary path.
        Returns the path to the downloaded file or None on failure.
        """
        try:
            download_url = self._get_gdrive_download_url(url)
            
            # Use a session for the request
            session = requests.Session()
            response = session.get(download_url, stream=True)
            response.raise_for_status()

            # Determine filename from Content-Disposition header
            content_disposition = response.headers.get('content-disposition')
            filename = None
            if content_disposition:
                filenames = re.findall('filename="(.+)"', content_disposition)
                if filenames:
                    filename = filenames[0]
            
            # If no filename in header, generate a random one and infer extension
            if not filename:
                content_type = response.headers.get('content-type', '')
                ext = '.tmp'
                if 'pdf' in content_type:
                    ext = '.pdf'
                elif 'word' in content_type or 'openxmlformats-officedocument' in content_type:
                    ext = '.docx'
                filename = f"{uuid.uuid4()}{ext}"

            # Sanitize filename and create temp path
            safe_filename = os.path.basename(filename).replace(" ", "_")
            temp_file_path = f"/tmp/{safe_filename}"
            
            # Write the file content
            with open(temp_file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"Successfully downloaded file to {temp_file_path}")
            return temp_file_path
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download file from URL {url}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during file download from {url}: {e}", exc_info=True)
            return None

    def import_from_local_file(self, uploaded_file):
        """
        Imports applicants from a local CSV or Excel file.
        """
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            elif uploaded_file.name.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(uploaded_file)
            else:
                raise ValueError("Unsupported file format. Please use CSV or Excel.")

            return self._process_dataframe(df)

        except Exception as e:
            logger.error(f"Failed to import from local file: {e}", exc_info=True)
            return 0, 0

    def import_from_resume(self, resume_url):
        """
        Imports a single applicant from a resume URL.
        """
        temp_file_path = self._download_file(resume_url)
        if not temp_file_path:
            return None
        
        try:
            # Process the downloaded resume
            resume_text = self.file_processor.extract_text(temp_file_path)
            if not resume_text:
                logger.error(f"Could not extract text from resume at {resume_url}")
                return None

            # Use AI to extract information
            ai_data = self.ai_classifier.extract_info("", "", resume_text)

            # Upload the resume to our Google Drive to get a persistent, shareable link
            drive_url = self.drive_handler.upload_to_drive(temp_file_path)

            # Prepare applicant data for insertion
            applicant_data = {
                'Name': ai_data.get('Name'),
                'Email': ai_data.get('Email'),
                'Phone': ai_data.get('Phone'),
                'Education': ai_data.get('Education'),
                'JobHistory': ai_data.get('JobHistory'),
                'Domain': ai_data.get('Domain', 'Other'),
                'CV_URL': drive_url,
                'Status': 'New'
            }
            
            # Insert into database (assuming no initial communication)
            return self.db_handler.insert_applicant_and_communication(applicant_data, {})

        except Exception as e:
            logger.error(f"Failed to process resume from URL {resume_url}: {e}", exc_info=True)
            return None
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)


    def _process_dataframe(self, df):
        """
        Processes a DataFrame of applicants, enriching data where necessary from resume links.
        """
        inserted_count = 0
        skipped_count = 0

        for _, row in df.iterrows():
            applicant_data = row.to_dict()
            temp_file_path = None

            # If essential data is missing but a resume link exists, try to fill the gaps
            is_missing_data = pd.isna(row.get('Name')) or pd.isna(row.get('Email'))
            has_resume_link = 'resume_link' in row and pd.notna(row['resume_link'])

            if is_missing_data and has_resume_link:
                temp_file_path = self._download_file(row['resume_link'])
                if temp_file_path:
                    try:
                        resume_text = self.file_processor.extract_text(temp_file_path)
                        ai_data = self.ai_classifier.extract_info("", "", resume_text)

                        # Fill in missing data from AI extraction
                        for key, value in ai_data.items():
                            # Only fill if the original data was empty
                            if key in applicant_data and pd.isna(applicant_data[key]):
                                applicant_data[key] = value
                    
                    except Exception as e:
                        logger.error(f"Could not process resume link {row['resume_link']} for enrichment: {e}", exc_info=True)

            # Insert into database
            if self.db_handler.insert_applicant_and_communication(applicant_data, {}):
                inserted_count += 1
            else:
                skipped_count += 1
            
            # Clean up the temporary file if it was downloaded
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        
        return inserted_count, skipped_count
