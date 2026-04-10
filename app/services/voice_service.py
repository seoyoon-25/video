"""음성 서비스 — Edge TTS 음성 목록 관리 및 미리듣기."""

import asyncio
from pathlib import Path
from typing import Optional

# Edge TTS 추천 음성 목록 (언어별)
EDGE_TTS_VOICES = [
    # 한국어
    {"id": "ko-KR-InJoonNeural", "name": "인준 (남성)", "lang": "ko", "gender": "male", "provider": "edge"},
    {"id": "ko-KR-SunHiNeural", "name": "선희 (여성)", "lang": "ko", "gender": "female", "provider": "edge"},
    {"id": "ko-KR-HyunsuNeural", "name": "현수 (남성)", "lang": "ko", "gender": "male", "provider": "edge"},
    {"id": "ko-KR-BongJinNeural", "name": "봉진 (남성)", "lang": "ko", "gender": "male", "provider": "edge"},
    {"id": "ko-KR-GookMinNeural", "name": "국민 (남성)", "lang": "ko", "gender": "male", "provider": "edge"},

    # 영어 (미국)
    {"id": "en-US-GuyNeural", "name": "Guy (Male)", "lang": "en", "gender": "male", "provider": "edge"},
    {"id": "en-US-JennyNeural", "name": "Jenny (Female)", "lang": "en", "gender": "female", "provider": "edge"},
    {"id": "en-US-AriaNeural", "name": "Aria (Female)", "lang": "en", "gender": "female", "provider": "edge"},
    {"id": "en-US-DavisNeural", "name": "Davis (Male)", "lang": "en", "gender": "male", "provider": "edge"},

    # 영어 (영국)
    {"id": "en-GB-RyanNeural", "name": "Ryan (Male, UK)", "lang": "en-GB", "gender": "male", "provider": "edge"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (Female, UK)", "lang": "en-GB", "gender": "female", "provider": "edge"},

    # 일본어
    {"id": "ja-JP-KeitaNeural", "name": "Keita (男性)", "lang": "ja", "gender": "male", "provider": "edge"},
    {"id": "ja-JP-NanamiNeural", "name": "Nanami (女性)", "lang": "ja", "gender": "female", "provider": "edge"},

    # 중국어 (간체)
    {"id": "zh-CN-YunxiNeural", "name": "云溪 (男)", "lang": "zh", "gender": "male", "provider": "edge"},
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (女)", "lang": "zh", "gender": "female", "provider": "edge"},

    # 스페인어
    {"id": "es-MX-JorgeNeural", "name": "Jorge (Hombre)", "lang": "es", "gender": "male", "provider": "edge"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira (Mujer)", "lang": "es", "gender": "female", "provider": "edge"},

    # 프랑스어
    {"id": "fr-FR-HenriNeural", "name": "Henri (Homme)", "lang": "fr", "gender": "male", "provider": "edge"},
    {"id": "fr-FR-DeniseNeural", "name": "Denise (Femme)", "lang": "fr", "gender": "female", "provider": "edge"},

    # 독일어
    {"id": "de-DE-ConradNeural", "name": "Conrad (Mann)", "lang": "de", "gender": "male", "provider": "edge"},
    {"id": "de-DE-KatjaNeural", "name": "Katja (Frau)", "lang": "de", "gender": "female", "provider": "edge"},

    # 포르투갈어
    {"id": "pt-BR-AntonioNeural", "name": "Antonio (Homem)", "lang": "pt", "gender": "male", "provider": "edge"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca (Mulher)", "lang": "pt", "gender": "female", "provider": "edge"},

    # 힌디어
    {"id": "hi-IN-MadhurNeural", "name": "Madhur (पुरुष)", "lang": "hi", "gender": "male", "provider": "edge"},
    {"id": "hi-IN-SwaraNeural", "name": "Swara (महिला)", "lang": "hi", "gender": "female", "provider": "edge"},
]

# 언어별 미리듣기 텍스트
PREVIEW_TEXTS = {
    "ko": "안녕하세요, 저는 AI 목소리입니다. 이 목소리로 영상을 제작해보세요.",
    "en": "Hello, I'm an AI voice. Create your video with this voice.",
    "en-GB": "Hello, I'm an AI voice. Create your video with this voice.",
    "ja": "こんにちは、私はAIの声です。この声で動画を作成してみてください。",
    "zh": "你好，我是AI语音。用这个声音来制作您的视频吧。",
    "es": "Hola, soy una voz de IA. Crea tu video con esta voz.",
    "fr": "Bonjour, je suis une voix IA. Créez votre vidéo avec cette voix.",
    "de": "Hallo, ich bin eine KI-Stimme. Erstellen Sie Ihr Video mit dieser Stimme.",
    "pt": "Olá, sou uma voz de IA. Crie seu vídeo com esta voz.",
    "hi": "नमस्ते, मैं एक AI आवाज़ हूँ। इस आवाज़ से अपना वीडियो बनाएं।",
}


def get_available_voices(lang: Optional[str] = None) -> list[dict]:
    """사용 가능한 음성 목록 반환."""
    voices = EDGE_TTS_VOICES.copy()

    if lang:
        voices = [v for v in voices if v["lang"] == lang or v["lang"].startswith(lang)]

    return voices


def get_voice_by_id(voice_id: str) -> Optional[dict]:
    """ID로 음성 정보 조회."""
    for voice in EDGE_TTS_VOICES:
        if voice["id"] == voice_id:
            return voice
    return None


def get_voice_preview_text(lang: str) -> str:
    """언어별 미리듣기 텍스트 반환."""
    return PREVIEW_TEXTS.get(lang, PREVIEW_TEXTS["en"])


async def _generate_preview_async(voice_id: str, text: str) -> bytes:
    """Edge TTS로 미리듣기 오디오 생성 (비동기)."""
    import edge_tts
    from io import BytesIO

    communicate = edge_tts.Communicate(text, voice_id)

    audio_data = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.write(chunk["data"])

    return audio_data.getvalue()


def generate_voice_preview(voice_id: str, lang: str = "ko") -> bytes:
    """음성 미리듣기 오디오 생성."""
    voice = get_voice_by_id(voice_id)
    if voice:
        lang = voice["lang"]

    text = get_voice_preview_text(lang)

    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _generate_preview_async(voice_id, text)
            )
            return future.result(timeout=30)
    except RuntimeError:
        return asyncio.run(_generate_preview_async(voice_id, text))


def get_languages() -> list[dict]:
    """지원 언어 목록."""
    return [
        {"code": "ko", "name": "한국어"},
        {"code": "en", "name": "English (US)"},
        {"code": "en-GB", "name": "English (UK)"},
        {"code": "ja", "name": "日本語"},
        {"code": "zh", "name": "中文"},
        {"code": "es", "name": "Español"},
        {"code": "fr", "name": "Français"},
        {"code": "de", "name": "Deutsch"},
        {"code": "pt", "name": "Português"},
        {"code": "hi", "name": "हिन्दी"},
    ]
