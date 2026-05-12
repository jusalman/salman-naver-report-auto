import os
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Scopes needed for Google Sheets and Drive
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.readonly'
]

def get_google_credentials():
    """
    Get or refresh Google OAuth credentials.
    Returns:
        google.oauth2.credentials.Credentials: The valid credentials, or None on failure.
    """
    creds = None
    token_path = os.getenv('GOOGLE_TOKEN_PATH', 'token/token.json')
    client_secret_path = os.getenv('GOOGLE_OAUTH_CLIENT_PATH', 'credentials/google_oauth_client.json')

    try:
        # Check if token.json exists
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Google credentials...")
                creds.refresh(Request())
            else:
                if not os.path.exists(client_secret_path):
                    raise FileNotFoundError(f"Google OAuth client file not found at '{client_secret_path}'. Please check credentials.")
                
                logger.info("Starting new Google OAuth flow. A browser window should open...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_secret_path, SCOPES)
                creds = flow.run_local_server(port=0)
                
            # Ensure the token directory exists before writing
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            
            # Save the credentials for the next run
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            logger.info("Google OAuth credentials saved successfully.")

        return creds

    except FileNotFoundError as e:
        logger.error(f"Authentication Error: {str(e)}")
        return None
    except Exception as e:
        # Avoid logging the raw exception to prevent leaking sensitive information
        logger.error("An unexpected error occurred during Google authentication. Please check your configuration.")
        return None

if __name__ == '__main__':
    # Simple test to verify authentication
    print("Testing Google Authentication...")
    credentials = get_google_credentials()
    if credentials:
        print("✅ Authentication Successful! Credentials object obtained.")
    else:
        print("❌ Authentication Failed. Please check the logs.")
