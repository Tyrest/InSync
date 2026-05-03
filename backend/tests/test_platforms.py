# Feature: backend-refactor, Property 4
"""Property tests for platform connector credential refresh — platform-agnostic from caller's perspective.

Validates: Requirements 2.2, 2.4
"""

import asyncio
import time

from app.platforms.spotify import SpotifyConnector
from app.platforms.youtube import YouTubeConnector
from hypothesis import given, settings
from hypothesis import strategies as st


@given(
    access_token=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
    expires_at=st.integers(min_value=int(time.time()) + 3600, max_value=int(time.time()) + 86400),
)
@settings(max_examples=50)
def test_spotify_refresh_credentials_returns_access_token_for_valid_creds(
    access_token: str,
    expires_at: int,
) -> None:
    """Property 4: SpotifyConnector.refresh_credentials returns a dict with an access_token key
    when the input credentials are valid (not expired), without the caller knowing the platform name.

    **Validates: Requirements 2.2, 2.4**
    """
    connector = SpotifyConnector()
    creds = {
        "access_token": access_token,
        "refresh_token": "some-refresh-token",
        "expires_at": expires_at,
    }

    result = asyncio.run(
        connector.refresh_credentials(
            credentials=creds,
            client_id="test-client-id",
            client_secret="test-client-secret",
        )
    )

    assert isinstance(result, dict), "refresh_credentials must return a dict"
    assert "access_token" in result, f"Result dict must contain 'access_token' key, got: {result.keys()}"
    assert result["access_token"], "access_token must be non-empty"


@given(
    access_token=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
    expires_at=st.integers(min_value=int(time.time()) + 3600, max_value=int(time.time()) + 86400),
)
@settings(max_examples=50)
def test_youtube_refresh_credentials_returns_access_token_for_valid_creds(
    access_token: str,
    expires_at: int,
) -> None:
    """Property 4: YouTubeConnector.refresh_credentials returns a dict with an access_token key
    when the input credentials are valid (not expired), without the caller knowing the platform name.

    **Validates: Requirements 2.2, 2.4**
    """
    connector = YouTubeConnector()
    creds = {
        "access_token": access_token,
        "refresh_token": "some-refresh-token",
        "expires_at": expires_at,
    }

    result = asyncio.run(
        connector.refresh_credentials(
            credentials=creds,
            client_id="test-client-id",
            client_secret="test-client-secret",
        )
    )

    assert isinstance(result, dict), "refresh_credentials must return a dict"
    assert "access_token" in result, f"Result dict must contain 'access_token' key, got: {result.keys()}"
    assert result["access_token"], "access_token must be non-empty"
