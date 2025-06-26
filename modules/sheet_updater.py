import json
from datetime import datetime
from googleapiclient.discovery import build
import pandas as pd
from zoneinfo import ZoneInfo
from utils.logger import logger

class SheetsUpdater:
    def __init__(self, credentials): # MODIFIED: Accept credentials
        """Initializes the SheetsUpdater with user-specific credentials."""
        try:
            self.sheets_service = build('sheets', 'v4', credentials=credentials)
            self.drive_service = build('drive', 'v3', credentials=credentials)
            logger.info("Google Sheets and Drive services initialized successfully for SheetsUpdater.")
        except Exception as e:
            logger.error(f"Failed to initialize Google services for SheetsUpdater: {e}", exc_info=True)
            self.sheets_service = None
            self.drive_service = None

    def read_sheet_data(self, spreadsheet_id, range_name='Sheet1!A1:Z'):
        """
        Reads data from a Google Sheet and returns it as a Pandas DataFrame.
        Assumes the first row is the header.
        """
        try:
            sheet = self.sheets_service.spreadsheets()
            result = sheet.values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])

            if not values:
                logger.warning(f"Google Sheet {spreadsheet_id} is empty or data could not be read.")
                return pd.DataFrame()

            # Assume the first row is the header, and the rest is data
            df = pd.DataFrame(values[1:], columns=values[0])
            logger.info(f"Successfully read {len(df)} rows from Google Sheet {spreadsheet_id}.")
            return df

        except Exception as e:
            logger.error(f"Failed to read data from Google Sheet {spreadsheet_id}: {e}", exc_info=True)
            return f"Error: Could not access the sheet. Please ensure it is public or shared with the service account."
        
    def create_export_sheet(self, data_to_export, columns):
        """
        Creates a new Google Sheet, populates it with data, and returns a shareable link.
        """
        try:
            # New, blank Google Sheet
            local_tz = ZoneInfo("Asia/Kolkata")
            timestamp_str = datetime.now(local_tz).strftime("%d-%b-%Y at %I.%M %p") 
            spreadsheet_title = f'Applicant Export ({timestamp_str})'

            spreadsheet_body = {
                'properties': {
                    'title': spreadsheet_title
                }
            }
            logger.info("Creating new Google Sheet...")
            spreadsheet = self.sheets_service.spreadsheets().create(body=spreadsheet_body).execute()
            spreadsheet_id = spreadsheet.get('spreadsheetId')
            spreadsheet_url = spreadsheet.get('spreadsheetUrl')
            logger.info(f"Successfully created sheet with ID: {spreadsheet_id}")

            # Prepare the data for writing 
            values_to_write = [columns]
            for applicant in data_to_export:
                row = [
                    applicant.get('Name', ''),
                    applicant.get('Email', ''),
                    applicant.get('Phone', ''),
                    applicant.get('Education', ''),
                    applicant.get('JobHistory', ''),
                    applicant.get('Resume', ''),
                    applicant.get('Role', ''),
                    applicant.get('Status', ''),
                    applicant.get('Feedback', '')
                ]
                values_to_write.append(row)
            
            #  Write the data to the new sheet
            write_body = {
                'values': values_to_write
            }
            logger.info(f"Writing {len(values_to_write) - 1} applicant records to the sheet...")
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='A1', 
                valueInputOption='USER_ENTERED',
                body=write_body
            ).execute()
            
            # Make the sheet publicy viewable (anyone with the link)
            logger.info("Setting sharing permissions for the new sheet...")
            permission_body = {'type': 'anyone', 'role': 'reader'}
            self.drive_service.permissions().create(
                fileId=spreadsheet_id,
                body=permission_body
            ).execute()

            logger.info(f"Export successful. Shareable URL: {spreadsheet_url}")
            return {
                "url": spreadsheet_url,
                "title": spreadsheet_title
            }

        except Exception as e:
            logger.error(f"Failed to create or update Google Sheet: {e}", exc_info=True)
            return None
