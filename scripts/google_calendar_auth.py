"""One-time Google Calendar authentication.

Run with:
    uv run python scripts/google_calendar_auth.py

Opens a browser for Google's OAuth consent screen, then caches the resulting
token to GOOGLE_CALENDAR_TOKEN_FILE. This is the ONLY place in the project
that launches an interactive OAuth flow - calendar_service itself never does,
so normal assistant execution never unexpectedly blocks on a browser login.
Re-run this script whenever calendar_service reports that authentication is
missing or has expired beyond automatic refresh. See README for the one-time
Google Cloud setup (enabling the Calendar API, creating OAuth credentials).
"""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from assistant.config.settings import get_settings
from assistant.services.calendar_service import SCOPES


def main() -> None:
    settings = get_settings()
    credentials_path = Path(settings.google_calendar_credentials_file)
    token_path = Path(settings.google_calendar_token_file)

    if not credentials_path.exists():
        raise SystemExit(
            f"OAuth client secret file not found at '{credentials_path}'. "
            "See README for how to download it from the Google Cloud console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    credentials = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json())
    print(f"Google Calendar authenticated. Token saved to '{token_path}'.")


if __name__ == "__main__":
    main()
