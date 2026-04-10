"""비디오 생성 라우트."""

import json
import time
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, g, Response, stream_with_context, current_app, jsonify
)

from ..auth.routes import login_required
from ..models import (
    create_generation, update_generation_status, update_generation_step,
    get_daily_usage, increment_daily_usage, can_generate,
    get_generation_by_job_id, get_generations_by_step
)
from ..services.voice_service import get_available_voices, get_voice_preview_text

generate_bp = Blueprint("generate", __name__, url_prefix="/generate")


def get_niche_choices():
    """사용 가능한 니치 목록을 가져옵니다."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from verticals.niche import list_niches, load_niche

    niches = list_niches()
    choices = []
    for n in niches:
        profile = load_niche(n)
        choices.append({
            "id": n,
            "name": profile.get("display_name", n),
            "description": profile.get("description", ""),
        })
    return choices


@generate_bp.route("/")
@login_required
def generate_page():
    """비디오 생성 페이지."""
    niches = get_niche_choices()
    voices = get_available_voices()

    can_gen, remaining = can_generate(g.user["id"], g.user["tier"])
    daily_limit = (
        current_app.config["PREMIUM_DAILY_LIMIT"]
        if g.user["tier"] == "premium"
        else current_app.config["FREE_DAILY_LIMIT"]
    )

    return render_template(
        "generate.html",
        niches=niches,
        voices=voices,
        can_generate=can_gen,
        remaining=remaining,
        daily_limit=daily_limit,
    )


@generate_bp.route("/start", methods=["POST"])
@login_required
def start_generation():
    """비디오 생성 시작 (SSE 스트림)."""
    can_gen, remaining = can_generate(g.user["id"], g.user["tier"])
    if not can_gen:
        return {"error": "일일 생성 한도를 초과했습니다."}, 429

    topic = request.form.get("topic", "").strip()
    niche = request.form.get("niche", "general")
    platform = request.form.get("platform", "shorts")
    voice_id = request.form.get("voice_id", "")

    if not topic:
        return {"error": "토픽을 입력해주세요."}, 400

    job_id = str(int(time.time() * 1000))

    create_generation(
        user_id=g.user["id"],
        job_id=job_id,
        topic=topic,
        niche=niche,
        platform=platform,
        voice_id=voice_id,
    )

    increment_daily_usage(g.user["id"])

    return {"job_id": job_id, "remaining": remaining - 1}


@generate_bp.route("/stream/<job_id>")
@login_required
def stream_progress(job_id: str):
    """SSE로 생성 진행 상황 스트리밍."""
    def generate():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

        from ..models import get_generation_by_job_id

        gen = get_generation_by_job_id(job_id)
        if not gen or gen["user_id"] != g.user["id"]:
            yield f"data: {json.dumps({'error': '작업을 찾을 수 없습니다.'})}\n\n"
            return

        topic = gen["topic"]
        niche = gen["niche"]
        platform = gen["platform"]
        voice_id = gen["voice_id"]

        steps = [
            {"id": "script", "name": "스크립트 작성", "progress": 0},
            {"id": "images", "name": "이미지 생성", "progress": 0},
            {"id": "voice", "name": "음성 생성", "progress": 0},
            {"id": "captions", "name": "자막 생성", "progress": 0},
            {"id": "assembly", "name": "영상 조립", "progress": 0},
        ]

        def send_progress(step_id, progress, message=""):
            for step in steps:
                if step["id"] == step_id:
                    step["progress"] = progress
                    break
            data = {
                "steps": steps,
                "current": step_id,
                "message": message,
            }
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            yield send_progress("script", 10, "드래프트 생성 중...")

            from verticals.draft import generate_draft
            from verticals.config import DRAFTS_DIR, MEDIA_DIR
            from verticals.state import PipelineState

            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

            draft = generate_draft(
                topic, "",
                niche=niche,
                platform=platform,
                provider="gemini",
            )
            draft["job_id"] = job_id

            out_path = DRAFTS_DIR / f"{job_id}.json"
            state = PipelineState(draft)
            state.complete_stage("research")
            state.complete_stage("draft")
            state.save(out_path)

            yield send_progress("script", 100, "스크립트 완료!")

            yield send_progress("images", 10, "B-Roll 이미지 생성 중...")

            from verticals.broll import generate_broll
            from verticals.niche import load_niche

            media_dir = MEDIA_DIR / job_id
            media_dir.mkdir(parents=True, exist_ok=True)

            profile = load_niche(niche)
            broll_prompts = draft.get("broll_prompts", [])

            for i, prompt in enumerate(broll_prompts):
                progress = 10 + int((i + 1) / len(broll_prompts) * 80)
                yield send_progress("images", progress, f"이미지 {i+1}/{len(broll_prompts)} 생성 중...")

            generate_broll(broll_prompts, media_dir, profile)
            yield send_progress("images", 100, "이미지 생성 완료!")

            yield send_progress("voice", 10, "음성 생성 중...")

            from verticals.tts import generate_voiceover
            from verticals.niche import get_voice_config

            voice_config = get_voice_config(profile, "edge_tts")
            if voice_id:
                voice_config["voice_id"] = voice_id

            script_text = draft.get("script", "")
            generate_voiceover(
                script_text,
                media_dir,
                lang="ko" if any('\uAC00' <= c <= '\uD7A3' for c in script_text) else "en",
                provider="edge",
                voice_config=voice_config,
            )

            yield send_progress("voice", 100, "음성 생성 완료!")

            yield send_progress("captions", 10, "자막 생성 중...")

            from verticals.captions import generate_captions

            audio_files = list(media_dir.glob("voiceover_*.mp3"))
            if audio_files:
                generate_captions(audio_files[0], media_dir)

            yield send_progress("captions", 100, "자막 생성 완료!")

            yield send_progress("assembly", 10, "영상 조립 중...")

            from verticals.assemble import assemble_video

            video_path = assemble_video(job_id, profile)
            yield send_progress("assembly", 100, "영상 조립 완료!")

            update_generation_status(job_id, "completed", str(video_path))

            final_data = {
                "steps": steps,
                "current": "done",
                "message": "완료!",
                "video_path": str(video_path),
                "title": draft.get("youtube_title", ""),
                "description": draft.get("youtube_description", ""),
            }
            yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            update_generation_status(job_id, "failed")
            error_data = {"error": str(e)}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────
# 단계별 워크플로우 라우트
# ─────────────────────────────────────────────────────

@generate_bp.route("/draft", methods=["POST"])
@login_required
def create_draft():
    """스크립트만 생성 (단계별 진행 모드)."""
    can_gen, remaining = can_generate(g.user["id"], g.user["tier"])
    if not can_gen:
        return jsonify({"error": "일일 생성 한도를 초과했습니다."}), 429

    topic = request.form.get("topic", "").strip()
    niche = request.form.get("niche", "general")
    platform = request.form.get("platform", "shorts")
    voice_id = request.form.get("voice_id", "")

    if not topic:
        return jsonify({"error": "토픽을 입력해주세요."}), 400

    job_id = str(int(time.time() * 1000))

    # 생성 레코드 생성 (step='draft_pending')
    create_generation(
        user_id=g.user["id"],
        job_id=job_id,
        topic=topic,
        niche=niche,
        platform=platform,
        voice_id=voice_id,
    )
    update_generation_step(job_id, "draft_pending")
    increment_daily_usage(g.user["id"])

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from verticals.draft import generate_draft
    from verticals.config import DRAFTS_DIR
    from verticals.state import PipelineState

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        draft = generate_draft(
            topic, "",
            niche=niche,
            platform=platform,
            provider="gemini",
        )
        draft["job_id"] = job_id

        out_path = DRAFTS_DIR / f"{job_id}.json"
        state = PipelineState(draft)
        state.complete_stage("research")
        state.complete_stage("draft")
        state.save(out_path)

        # 스크립트 데이터 저장
        script_data = json.dumps(draft, ensure_ascii=False)
        update_generation_step(job_id, "draft_review", script_data)
        update_generation_status(job_id, "draft_ready")

        return jsonify({
            "job_id": job_id,
            "remaining": remaining - 1,
            "script": draft.get("script", ""),
            "broll_prompts": draft.get("broll_prompts", []),
            "youtube_title": draft.get("youtube_title", ""),
            "youtube_description": draft.get("youtube_description", ""),
        })

    except Exception as e:
        update_generation_status(job_id, "failed")
        return jsonify({"error": str(e)}), 500


@generate_bp.route("/draft/<job_id>", methods=["GET"])
@login_required
def get_draft(job_id: str):
    """스크립트 조회."""
    gen = get_generation_by_job_id(job_id)
    if not gen or gen["user_id"] != g.user["id"]:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404

    if gen["step"] not in ("draft_review", "draft_pending"):
        return jsonify({"error": "이미 진행 중이거나 완료된 작업입니다."}), 400

    script_data = gen.get("script_data")
    if not script_data:
        return jsonify({"error": "스크립트 데이터가 없습니다."}), 404

    draft = json.loads(script_data)
    return jsonify({
        "job_id": job_id,
        "topic": gen["topic"],
        "niche": gen["niche"],
        "platform": gen["platform"],
        "voice_id": gen["voice_id"],
        "script": draft.get("script", ""),
        "broll_prompts": draft.get("broll_prompts", []),
        "youtube_title": draft.get("youtube_title", ""),
        "youtube_description": draft.get("youtube_description", ""),
    })


@generate_bp.route("/draft/<job_id>", methods=["POST"])
@login_required
def update_draft(job_id: str):
    """스크립트 수정 저장."""
    gen = get_generation_by_job_id(job_id)
    if not gen or gen["user_id"] != g.user["id"]:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404

    if gen["step"] != "draft_review":
        return jsonify({"error": "수정할 수 없는 상태입니다."}), 400

    script_data = gen.get("script_data")
    if not script_data:
        return jsonify({"error": "스크립트 데이터가 없습니다."}), 404

    draft = json.loads(script_data)

    # 요청 데이터로 업데이트
    data = request.get_json()
    if data.get("script"):
        draft["script"] = data["script"]
    if data.get("broll_prompts"):
        draft["broll_prompts"] = data["broll_prompts"]
    if data.get("youtube_title"):
        draft["youtube_title"] = data["youtube_title"]
    if data.get("youtube_description"):
        draft["youtube_description"] = data["youtube_description"]

    # 드래프트 파일도 업데이트
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from verticals.config import DRAFTS_DIR

    out_path = DRAFTS_DIR / f"{job_id}.json"
    if out_path.exists():
        with open(out_path, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        state_data.update(draft)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

    new_script_data = json.dumps(draft, ensure_ascii=False)
    update_generation_step(job_id, "draft_review", new_script_data)

    return jsonify({"success": True})


@generate_bp.route("/continue/<job_id>", methods=["POST"])
@login_required
def continue_generation(job_id: str):
    """스크립트 확정 후 다음 단계 진행 (SSE 스트림)."""
    gen = get_generation_by_job_id(job_id)
    if not gen or gen["user_id"] != g.user["id"]:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404

    if gen["step"] != "draft_review":
        return jsonify({"error": "진행할 수 없는 상태입니다."}), 400

    # 진행 중 상태로 변경
    update_generation_step(job_id, "images")
    update_generation_status(job_id, "processing")

    return jsonify({"job_id": job_id})


@generate_bp.route("/stream-continue/<job_id>")
@login_required
def stream_continue(job_id: str):
    """스크립트 확정 후 나머지 단계 SSE 스트리밍."""
    def generate():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

        gen = get_generation_by_job_id(job_id)
        if not gen or gen["user_id"] != g.user["id"]:
            yield f"data: {json.dumps({'error': '작업을 찾을 수 없습니다.'})}\n\n"
            return

        script_data = gen.get("script_data")
        if not script_data:
            yield f"data: {json.dumps({'error': '스크립트 데이터가 없습니다.'})}\n\n"
            return

        draft = json.loads(script_data)
        niche = gen["niche"]
        voice_id = gen["voice_id"]

        steps = [
            {"id": "images", "name": "이미지 생성", "progress": 0},
            {"id": "voice", "name": "음성 생성", "progress": 0},
            {"id": "captions", "name": "자막 생성", "progress": 0},
            {"id": "assembly", "name": "영상 조립", "progress": 0},
        ]

        def send_progress(step_id, progress, message=""):
            for step in steps:
                if step["id"] == step_id:
                    step["progress"] = progress
                    break
            data = {
                "steps": steps,
                "current": step_id,
                "message": message,
            }
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            yield send_progress("images", 10, "B-Roll 이미지 생성 중...")

            from verticals.broll import generate_broll
            from verticals.niche import load_niche
            from verticals.config import MEDIA_DIR

            media_dir = MEDIA_DIR / job_id
            media_dir.mkdir(parents=True, exist_ok=True)

            profile = load_niche(niche)
            broll_prompts = draft.get("broll_prompts", [])

            for i, prompt in enumerate(broll_prompts):
                progress = 10 + int((i + 1) / len(broll_prompts) * 80)
                yield send_progress("images", progress, f"이미지 {i+1}/{len(broll_prompts)} 생성 중...")

            generate_broll(broll_prompts, media_dir, profile)
            yield send_progress("images", 100, "이미지 생성 완료!")

            yield send_progress("voice", 10, "음성 생성 중...")

            from verticals.tts import generate_voiceover
            from verticals.niche import get_voice_config

            voice_config = get_voice_config(profile, "edge_tts")
            if voice_id:
                voice_config["voice_id"] = voice_id

            script_text = draft.get("script", "")
            generate_voiceover(
                script_text,
                media_dir,
                lang="ko" if any('\uAC00' <= c <= '\uD7A3' for c in script_text) else "en",
                provider="edge",
                voice_config=voice_config,
            )

            yield send_progress("voice", 100, "음성 생성 완료!")

            yield send_progress("captions", 10, "자막 생성 중...")

            from verticals.captions import generate_captions

            audio_files = list(media_dir.glob("voiceover_*.mp3"))
            if audio_files:
                generate_captions(audio_files[0], media_dir)

            yield send_progress("captions", 100, "자막 생성 완료!")

            yield send_progress("assembly", 10, "영상 조립 중...")

            from verticals.assemble import assemble_video

            video_path = assemble_video(job_id, profile)
            yield send_progress("assembly", 100, "영상 조립 완료!")

            update_generation_step(job_id, "completed")
            update_generation_status(job_id, "completed", str(video_path))

            final_data = {
                "steps": steps,
                "current": "done",
                "message": "완료!",
                "video_path": str(video_path),
                "title": draft.get("youtube_title", ""),
                "description": draft.get("youtube_description", ""),
            }
            yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            update_generation_status(job_id, "failed")
            error_data = {"error": str(e)}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@generate_bp.route("/drafts")
@login_required
def list_drafts():
    """검토 대기 중인 스크립트 목록."""
    drafts = get_generations_by_step(g.user["id"], "draft_review")
    return jsonify({"drafts": drafts})
