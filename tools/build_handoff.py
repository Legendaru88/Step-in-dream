"""Build a deterministic source-only ZIP, with or without Git metadata (offline)."""

import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "tggoals-source-2026-10-19.zip"
ROOT_FILES = {
    "README.md", "TASKS", "requirements.txt", "Dockerfile", "docker-compose.yml",
    "alembic.ini", ".gitignore", ".dockerignore",
}
# Only source/documentation formats, never arbitrary files from these directories.
SOURCE_TYPES = {"app": {".py"}, "migrations": {".py", ".mako"},
                "tests": {".py"}, "docs": {".md"}, "tools": {".py"},
                "handoff": {".py", ".md", ".txt", ".yml", ".sh"}}
ENV_TEMPLATE = """BOT_TOKEN=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-6-luna
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions
DATABASE_URL=sqlite+aiosqlite:///./data/tggoals.db
API_PORT=8000
IMAGE_ANALYSIS_MODE=direct
VISION_MODEL=qwen/qwen3-vl-30b-a3b-instruct
IMAGE_MAX_BYTES=8388608
TELEGRAM_PROXY_URL=
OPENROUTER_PROXY_URL=
"""


def source_paths():
    """Use the same bounded filesystem selection in a checkout and an extracted ZIP."""
    candidates = [ROOT / name for name in ROOT_FILES]
    candidates += [ROOT / "handoff/tunnel/Dockerfile", ROOT / "handoff/tunnel/known_hosts"]
    for directory, suffixes in SOURCE_TYPES.items():
        start = ROOT / directory
        if not start.is_symlink():
            candidates.extend(p for p in start.rglob("*") if p.suffix in suffixes)
    for full_path in sorted(candidates):
        relative = full_path.relative_to(ROOT)
        if "secrets" in relative.parts:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            if relative.as_posix() not in ROOT_FILES:
                continue
        if any(p.is_symlink() for p in [full_path, *full_path.parents]):
            continue
        if full_path.is_file():
            yield relative.as_posix(), full_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = {name: path.read_bytes() for name, path in source_paths()}
    # Never read an existing .env or its variants, even the local example.
    entries[".env.example"] = ENV_TEMPLATE.encode()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(f"tggoals/{name}", date_time=(2026, 10, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    print(f"{output}: {len(entries)} files; sha256={digest}")


if __name__ == "__main__":
    main()
