# Changelog

## [3.0.0] — 2026-04-02

### Added
- **Niche support** — `--niche` flag on `draft` and `run` commands. Injects a one-line niche context into the Claude prompt (e.g. `Niche: fitness — keep tone and examples relevant to this audience.`). Supported niches: gaming, finance, fitness, tech, food, travel, general.
- **NewsAPI source** — `pipeline/topics/newsapi.py` (`NewsAPISource`). Fetches top headlines via the NewsAPI REST API. Silently skipped when `NEWSAPI_KEY` is absent. API key sent via `X-Api-Key` header (not URL param). Rank-based trending score (1.0 → 0.3 decay).
- **Multi-platform scaffold** — `--platform` flag with choices `shorts`, `reels`, `tiktok`, `all`. Platform-specific script length hints via `PLATFORM_CONFIGS` in `config.py`. All platforms share 9:16 portrait for now; expand `PLATFORM_CONFIGS` to diverge per platform.
- **`PLATFORM_CONFIGS`** dict in `config.py` — label + `max_script_words` per platform.
- **`NICHE_TO_SUBREDDITS`** dict in `config.py` — niche → default subreddit list for topic discovery.
- **`get_newsapi_key()`** helper in `config.py` — resolves `NEWSAPI_KEY` from env then config.json.
- `NEWSAPI_KEY` documented in README configuration table.

### Changed
- `generate_draft()` signature: added `niche` and `platform` parameters (both default to safe values).
- `draft` output JSON now includes `niche` and `platform` fields for downstream use.
- README: bumped to v3.0.0, added Niche Examples table, added NewsAPI to topic sources table, added autopilot CTA footer.

## [2.1.0] — 2026-02-27

Security audit fixes ported to v2 modular architecture.

### Security
- **Fix TOCTOU race in credential file writes.** `write_secret_file()` in `pipeline/config.py` now uses `os.open()` with `0o600` mode to atomically create files with correct permissions, eliminating the brief window where credentials were world-readable. Also applied to `scripts/setup_youtube_oauth.py`.
- **Escape ffmpeg concat file paths.** Single quotes in file paths are now properly escaped in `pipeline/assemble.py` for the ffmpeg concat demuxer.
- **Pin all dependency versions.** `pyproject.toml` and `requirements.txt` now use compatible-release bounds (e.g., `anthropic>=0.39.0,<1.0`) to reduce supply-chain risk.

### Fixed
- **Clear error on expired OAuth token without refresh token.** `pipeline/upload.py` now raises a descriptive `RuntimeError` instead of silently attempting to use expired credentials.

### Added
- Security section in `README.md` documenting all hardening measures.
- `CHANGELOG.md` (this file).

## [2.0.0] — 2026-02-27

Major restructure: modular `pipeline/` package with new features.

### Added
- **Burned-in captions** — word-by-word highlight via ASS subtitles (Whisper word timestamps).
- **Background music** — bundled royalty-free tracks with automatic voice-ducking.
- **Topic engine** — discover trending topics from Reddit, RSS, Google Trends, Twitter, TikTok.
- **Thumbnail generation** — Gemini Imagen + Pillow text overlay, auto-uploaded.
- **Resume capability** — pipeline state tracked per stage, re-runs skip completed work.
- **Retry logic** — `@with_retry` exponential backoff on all API calls.
- **Structured logging** — file + console logging, `--verbose` for debug output.
- **Claude Max support** — use Claude CLI as alternative to API key.
- **78 tests** — comprehensive test suite across all modules.
- `pyproject.toml` with proper packaging.

### Security (carried forward from audit)
- Gemini API key sent via `x-goog-api-key` header, not URL query parameter.
- Sanitized API error responses — no credential reflection.
- YouTube OAuth scope narrowed to `youtube.upload` + `youtube.force-ssl`.
- Default upload privacy set to `private`.
- Prompt injection mitigation — snippet truncation (300 chars) + boundary markers.
- LLM output validation — type-checking on all draft fields.
- `.gitignore` covers credential files, `.env`, output directories.

## [1.0.0] — 2026-02-27

Initial release. Single-file pipeline: draft → produce → upload.
