# Repository Guidelines

## Project Structure & Module Organization

- `elevenlabs_tts_client.py`: Main CLI client (Reader workflow and streaming).
- `tts`: Convenience wrapper script (auto-extracts/caches tokens).
- `token_manager.py`: Firebase token caching and refresh.
- `utils/`: Flow parsing and debugging helpers.
- `tests/`: Script-style tests (`test_*.py`) runnable with Python.
- `test-results/`: Output artifacts from sample runs.
- `examples.sh`: End-to-end usage examples.
- `requirements.txt`: Python runtime dependencies.
- `tmp/` (git-ignored): Large or temporary data. Secrets are ignored via `.gitignore` (e.g., `tokens_cache.json`, `flows.*`).

## Build, Test, and Development Commands

- Install deps: `pip install -r requirements.txt`
- Make scripts executable: `chmod +x elevenlabs_tts_client.py tts`
- Smoke test (no secrets in shell): `./tts --list-voices`
- Run specific tests: `python tests/test_basic.py` or `python tests/test_reader_api.py`
- Run all tests: `for f in tests/test_*.py; do python "$f"; done`
- Local TTS example: `./tts --voice-id "<VOICE>" --text "Hello" --method reader --play`
  - Requires `mpv` or `ffplay` installed for `--play`.

## Coding Style & Naming Conventions

- Python 3.10+; 4-space indentation; keep imports grouped (stdlib, third-party, local).
- Prefer type hints and concise docstrings.
- Naming: `snake_case` for functions/vars, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- CLI flags use long, hyphenated names (e.g., `--firebase-refresh-token`).
- No repo-enforced linter/formatter; match existing style in files.

## Testing Guidelines

- Tests live in `tests/` and are runnable directly with Python.
- Keep unit tests offline by default; gate networked checks behind explicit flags or skip when deps are missing.
- Add new tests as `tests/test_<area>.py` with clear assertions.
- Validate token/cache behaviors without real secrets.

## Commit & Pull Request Guidelines

- Messages: prefer Conventional Commits (e.g., `feat:`, `fix:`, `chore:`). History shows mixed `cleanup` and `chore(init)`; use Conventional going forward.
- PRs must include: purpose, scope, test plan (exact commands), and sample output (redacted). Link related issues.
- If touching auth/streaming, include a short architecture note and logs with secrets removed.

## Security & Configuration Tips

- Never commit tokens, device IDs, or raw traffic. `.gitignore` already excludes `tokens_cache.json`, `flows.*`, and `tmp/`.
- Prefer `./tts` or `python get_refresh_token.py` to manage tokens; use env vars like `FIREBASE_REFRESH_TOKEN` when needed.
- Store large or sensitive artifacts in `tmp/` locally only.

