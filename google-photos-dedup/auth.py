"""Google Photos API authentication and client setup."""

import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"


def get_authenticated_service():
    """Authenticate and return a Google Photos API service client."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"'{CREDENTIALS_PATH}' not found. Download OAuth credentials from "
                    "Google Cloud Console and save as 'credentials.json'."
                )
            print("Starting OAuth flow — a browser window will open...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print("Authentication successful. Token saved.")

    return creds


def get_photos_api_url():
    """Return the base URL for the Photos Library API (REST)."""
    return "https://photoslibrary.googleapis.com/v1"
