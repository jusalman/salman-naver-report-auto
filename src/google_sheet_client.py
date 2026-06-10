import logging
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from src.google_auth import get_google_credentials

logger = logging.getLogger(__name__)

RETRYABLE_READ_STATUSES = {429, 500, 502, 503, 504}

class GoogleSheetClient:
    def __init__(self):
        self.creds = get_google_credentials()
        if not self.creds:
            raise ValueError("Google credentials are not available. Please run authentication first.")
        
        try:
            self.service = build('sheets', 'v4', credentials=self.creds)
        except Exception as e:
            logger.error("Failed to build Google Sheets service.")
            raise

    def get_sheet_data(self, spreadsheet_id: str, range_name: str, value_render_option=None) -> list[list]:
        """
        Reads data from a specific range in a Google Sheet.
        Returns a list of lists representing rows and columns.
        Data is normalized so that all rows have the same length as the header.
        """
        for attempt in range(4):
            try:
                sheet = self.service.spreadsheets()
                request = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name)
                if value_render_option:
                    request = sheet.values().get(
                        spreadsheetId=spreadsheet_id,
                        range=range_name,
                        valueRenderOption=value_render_option,
                    )
                result = request.execute()
                values = result.get('values', [])
                return self.normalize_sheet_rows(values)
            except HttpError as err:
                status = err.resp.status
                if status in RETRYABLE_READ_STATUSES and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                logger.error(f"HTTP Error occurred while accessing Google Sheets API: {status}")
                return []
            except Exception as e:
                logger.error(f"An unexpected error occurred while fetching sheet data: {e}")
                return []

    @staticmethod
    def normalize_sheet_rows(rows: list[list]) -> list[list]:
        """
        보정 로직:
        1. 첫 번째 행을 header로 사용합니다.
        2. 각 data row가 header보다 짧으면 빈 문자열 ""로 padding합니다.
        3. 각 data row가 header보다 길면 header 길이에 맞춰 truncate합니다.
        4. 완전히 빈 행은 제외합니다.
        """
        if not rows:
            return []
        
        header = rows[0]
        header_len = len(header)
        
        normalized = [header]
        for row in rows[1:]:
            # Padding
            if len(row) < header_len:
                row = row + [""] * (header_len - len(row))
            # Truncating
            elif len(row) > header_len:
                row = row[:header_len]
            
            # 완전히 빈 행 제외 (모든 셀이 공백이거나 빈 문자열인 경우)
            if any(str(cell).strip() != "" for cell in row):
                normalized.append(row)
                
        return normalized

    def append_sheet_data(self, spreadsheet_id: str, range_name: str, values: list[list], value_input_option: str = 'USER_ENTERED'):
        """
        Appends data to a Google Sheet.
        """
        try:
            sheet = self.service.spreadsheets()
            body = {
                'values': values
            }
            result = sheet.values().append(
                spreadsheetId=spreadsheet_id, 
                range=range_name,
                valueInputOption=value_input_option,
                body=body
            ).execute()
            return result
        except HttpError as err:
            logger.error(f"HTTP Error occurred while appending to Google Sheets API: {err.resp.status}")
            return None
        except Exception as e:
            logger.error("An unexpected error occurred while appending sheet data.")
            return None

    def get_sheet_info(self, spreadsheet_id: str):
        """Returns spreadsheet info including list of sheets."""
        for attempt in range(4):
            try:
                return self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            except HttpError as err:
                status = err.resp.status
                if status in RETRYABLE_READ_STATUSES and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                logger.error(f"HTTP Error getting sheet info: {status}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error getting sheet info: {e}")
                return None

    def add_sheet(self, spreadsheet_id: str, title: str):
        """Adds a new sheet (tab) to the spreadsheet."""
        requests = [{
            'addSheet': {
                'properties': {
                    'title': title
                }
            }
        }]
        try:
            return self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()
        except Exception as e:
            logger.error(f"Failed to add sheet '{title}': {e}")
            return None

    def update_sheet_data(self, spreadsheet_id: str, range_name: str, values: list[list], value_input_option: str = 'USER_ENTERED'):
        """Updates data in a specific range."""
        try:
            body = {'values': values}
            return self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                body=body
            ).execute()
        except Exception as e:
            logger.error(f"Failed to update sheet data at '{range_name}': {e}")
            return None

    def clear_sheet_data(self, spreadsheet_id: str, range_name: str):
        """Clears data in a specific range."""
        try:
            return self.service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()
        except Exception as e:
            logger.error(f"Failed to clear sheet data at '{range_name}': {e}")
            return None
