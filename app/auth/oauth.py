"""Google OAuth 2.0 헬퍼."""

import os
import json
import secrets
from urllib.parse import urlencode

import requests
from flask import current_app, url_for, session


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def generate_oauth_state() -> str:
    """CSRF 방지용 OAuth state 토큰 생성 및 세션 저장."""
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return state


def verify_oauth_state(state: str) -> bool:
    """OAuth state 토큰 검증."""
    expected_state = session.pop("oauth_state", None)
    return expected_state is not None and secrets.compare_digest(expected_state, state)


def get_google_auth_url() -> str:
    """Google OAuth 인증 URL 생성."""
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID가 설정되지 않았습니다.")

    redirect_uri = url_for("auth.google_callback", _external=True)
    state = generate_oauth_state()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }

    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def handle_google_callback(code: str) -> dict:
    """Google OAuth 콜백 처리, 사용자 정보 반환."""
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("Google OAuth 설정이 완료되지 않았습니다.")

    redirect_uri = url_for("auth.google_callback", _external=True)

    # 토큰 교환
    token_response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )

    if token_response.status_code != 200:
        raise ValueError(f"토큰 교환 실패: {token_response.text}")

    tokens = token_response.json()
    access_token = tokens.get("access_token")

    if not access_token:
        raise ValueError("액세스 토큰을 받지 못했습니다.")

    # 사용자 정보 조회
    userinfo_response = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )

    if userinfo_response.status_code != 200:
        raise ValueError(f"사용자 정보 조회 실패: {userinfo_response.text}")

    return userinfo_response.json()
