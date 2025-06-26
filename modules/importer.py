import pandas as pd
from urllib.parse import urlparse
import requests
import io

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

    def import_from_local_file(self, uploaded_file):
        """
        Imports applicants from a local CSV or Excel file.

        Args:
            uploaded_file: The uploaded file object from Streamlit.

        Returns:
            A tuple of (inserted_count, skipped_count).
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

        Args:
            resume_url (str): The URL to the applicant's resume.

        Returns:
            The ID of the newly created applicant, or None if failed.
        """
        try:
            # Create a temporary file path
            temp_file_path = f"/tmp/{resume_url.split('/')[-1]}"

            # Download the resume
            response = requests.get(resume_url)
            response.raise_for_status()
            with open(temp_file_path, 'wb') as f:
                f.write(response.content)

            # Process the resume
            resume_text = self.file_processor.extract_text(temp_file_path)
            if not resume_text:
                logger.error(f"Could not extract text from resume at {resume_url}")
                return None

            # Use AI to extract information
            ai_data = self.ai_classifier.extract_info("", "", resume_text)

            # Upload the resume to Google Drive to get a shareable link
            drive_url = self.drive_handler.upload_to_drive(temp_file_path)

            # Prepare applicant data
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
            
            # Insert into database
            return self.db_handler.insert_applicant_and_communication(applicant_data, {})

        except Exception as e:
            logger.error(f"Failed to import from resume URL {resume_url}: {e}", exc_info=True)
            return None

    def _process_dataframe(self, df):
        """
        Processes a DataFrame of applicants, enriching data where necessary.

        Args:
            df (pd.DataFrame): The DataFrame of applicants to process.

        Returns:
            A tuple of (inserted_count, skipped_count).
        """
        inserted_count = 0
        skipped_count = 0

        for _, row in df.iterrows():
            applicant_data = row.to_dict()

            # If essential data is missing, try to get it from the resume
            if pd.isna(row.get('Name')) or pd.isna(row.get('Email')) and 'resume_link' in row and not pd.isna(row['resume_link']):
                try:
                    # Create a temporary file path
                    temp_file_path = f"/tmp/{row['resume_link'].split('/')[-1]}"

                    # Download the resume
                    response = requests.get(row['resume_link'])
                    response.raise_for_status()

                    with open(temp_file_path, 'wb') as f:
                        f.write(response.content)
                    
                    resume_text = self.file_processor.extract_text(temp_file_path)
                    ai_data = self.ai_classifier.extract_info("", "", resume_text)

                    # Fill in missing data
                    for key, value in ai_data.items():
                        if key in applicant_data and pd.isna(applicant_data[key]):
                            applicant_data[key] = value
                
                except Exception as e:
                    logger.error(f"Could not process resume link {row['resume_link']}: {e}", exc_info=True)

            # Insert into database
            if self.db_handler.insert_applicant_and_communication(applicant_data, {}):
                inserted_count += 1
            else:
                skipped_count += 1
        
        return inserted_count, skipped_count
