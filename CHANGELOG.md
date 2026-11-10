# Changelog

## 0.2.1 — 2026-11-10

### Fixed
- Live viewer no longer crashes on torn ffmpeg PNG frames (`SyntaxError: broken PNG file`).
- Capture now streams PNG frames over a pipe and publishes each complete frame with an atomic replace.

## 0.2.0 — 2026-11-10

### Changed
- Skill description tightened for Agent Skills catalogs.
- Docs note Agent Skills packaging and Claude Opus/Fable computer-use guidance without hard-pinning a model.
- Package / plugin version bumped to 0.2.0.
