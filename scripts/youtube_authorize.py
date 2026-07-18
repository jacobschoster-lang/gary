"""One-time helper to mint a YouTube upload refresh token.

Run this LOCALLY (it needs a browser) using the Google account that owns the
target channel (@StickfigureFinance-r8m). It prints a refresh token that you
then store as the ``YOUTUBE_REFRESH_TOKEN`` secret.

Prerequisites:
  1. Create a Google Cloud project and enable "YouTube Data API v3".
  2. Create an OAuth client (type: Desktop app). Download the client JSON, or
     note the client id/secret.

Usage:
    export YOUTUBE_CLIENT_ID=...        # or pass --client-secrets client.json
    export YOUTUBE_CLIENT_SECRET=...
    python scripts/youtube_authorize.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mint a YouTube upload refresh token")
    parser.add_argument("--client-secrets", help="path to OAuth client JSON (optional)")
    args = parser.parse_args(argv)

    from google_auth_oauthlib.flow import InstalledAppFlow

    if args.client_secrets:
        flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, SCOPES)
    else:
        client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        if not (client_id and client_secret):
            print(
                "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET, "
                "or pass --client-secrets client.json",
                file=sys.stderr,
            )
            return 2
        config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(config, SCOPES)

    creds = flow.run_local_server(port=0)
    print("\n=== SUCCESS ===")
    print("Store this as the YOUTUBE_REFRESH_TOKEN secret:\n")
    print(creds.refresh_token)
    print("\n(full token json for reference):")
    print(json.dumps(json.loads(creds.to_json()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
