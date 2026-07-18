"""Real YouTube Data API v3 uploader (issue #6, publishing side).

Uploading requires OAuth 2.0 on the account that owns the target channel; an API
key is not sufficient. Provide credentials via environment variables:

    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN     # minted once via scripts/youtube_authorize.py

Optional:
    YOUTUBE_PRIVACY           # "private" (default) | "unlisted" | "public"

``YouTubeUploader.from_env()`` returns ``None`` when credentials are absent, so
callers can fall back to a safe dry-run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


@dataclass
class YouTubeUploader:
    client_id: str
    client_secret: str
    refresh_token: str
    privacy: str = "private"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> YouTubeUploader | None:
        env = env if env is not None else dict(os.environ)
        client_id = env.get("YOUTUBE_CLIENT_ID")
        client_secret = env.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = env.get("YOUTUBE_REFRESH_TOKEN")
        if not (client_id and client_secret and refresh_token):
            return None
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            privacy=env.get("YOUTUBE_PRIVACY", "private"),
        )

    def _service(self) -> Any:
        # Imported lazily so the rest of the app runs without google libs loaded.
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_uri=TOKEN_URI,
            scopes=UPLOAD_SCOPES,
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str] | None = None,
        thumbnail_path: str | None = None,
    ) -> dict[str, Any]:
        """Upload ``video_path`` and return the created video resource."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"video file not found: {video_path}")

        from googleapiclient.http import MediaFileUpload

        youtube = self._service()
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags or [],
                "categoryId": "25",  # News & Politics; adjust as needed
            },
            "status": {"privacyStatus": self.privacy, "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _status, response = request.next_chunk()

        video_id = response["id"]
        if thumbnail_path and os.path.exists(thumbnail_path):
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path),
            ).execute()

        return {
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "privacy": self.privacy,
        }
