"""AJAX API 라우트."""

import io
import logging
from flask import Blueprint, jsonify, request, g, send_file

from ..auth.routes import login_required
from ..services.voice_service import get_available_voices, generate_voice_preview

api_bp = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@api_bp.route("/voices")
def list_voices():
    """음성 목록 조회."""
    lang = request.args.get("lang", "")
    provider = request.args.get("provider", "")

    voices = get_available_voices()

    if lang:
        voices = [v for v in voices if v["lang"] == lang or v["lang"].startswith(lang)]

    if provider:
        voices = [v for v in voices if v["provider"] == provider]

    return jsonify(voices)


@api_bp.route("/voices/preview/<voice_id>")
def preview_voice(voice_id: str):
    """음성 미리듣기."""
    lang = request.args.get("lang", "ko")

    try:
        audio_data = generate_voice_preview(voice_id, lang)
        return send_file(
            io.BytesIO(audio_data),
            mimetype="audio/mpeg",
            download_name=f"preview_{voice_id}.mp3",
        )
    except Exception as e:
        logger.error(f"음성 미리듣기 실패 voice_id={voice_id}: {e}", exc_info=True)
        return jsonify({"error": "음성 미리듣기를 불러올 수 없습니다."}), 500


@api_bp.route("/usage")
@login_required
def get_usage():
    """오늘 사용량 조회."""
    from ..models import get_daily_usage, can_generate
    from flask import current_app

    used = get_daily_usage(g.user["id"])
    can_gen, remaining = can_generate(g.user["id"], g.user["tier"])

    daily_limit = (
        current_app.config["PREMIUM_DAILY_LIMIT"]
        if g.user["tier"] == "premium"
        else current_app.config["FREE_DAILY_LIMIT"]
    )

    return jsonify({
        "used": used,
        "remaining": remaining,
        "limit": daily_limit,
        "can_generate": can_gen,
    })
