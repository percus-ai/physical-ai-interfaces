"""Authentication models."""

from pydantic import BaseModel, Field


class AuthLoginRequest(BaseModel):
    """Supabase login request."""

    email: str = Field(..., description="Login email")
    password: str = Field(..., description="Login password")


class AuthLoginResponse(BaseModel):
    """Supabase login response."""

    success: bool = Field(..., description="Login success")
    user_id: str = Field(..., description="Supabase user id")
    expires_at: int | None = Field(None, description="Access token expiry (unix time)")
    session_expires_at: int | None = Field(
        None, description="Session expiry based on refresh token (unix time)"
    )
    access_token: str | None = Field(None, description="Access token (CLI only)")
    refresh_token: str | None = Field(None, description="Refresh token (CLI only)")


class AuthStatusResponse(BaseModel):
    """Supabase auth status response."""

    authenticated: bool = Field(..., description="Whether session is available")
    user_id: str | None = Field(None, description="Supabase user id")
    expires_at: int | None = Field(None, description="Access token expiry (unix time)")
    session_expires_at: int | None = Field(
        None, description="Session expiry based on refresh token (unix time)"
    )


class AuthTokenResponse(BaseModel):
    """Supabase auth token response (for WebSocket clients)."""

    access_token: str = Field(..., description="Access token")
    refresh_token: str | None = Field(None, description="Refresh token (optional)")
    user_id: str | None = Field(None, description="Supabase user id")
    expires_at: int | None = Field(None, description="Access token expiry (unix time)")
    session_expires_at: int | None = Field(
        None, description="Session expiry based on refresh token (unix time)"
    )
