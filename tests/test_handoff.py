"""Recipient can rebuild without Git, without leaking local runtime files."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def test_source_archive_rebuild_and_exclusions(tmp_path):
    root = tmp_path / "source"
    (root / "tools").mkdir(parents=True)
    builder = Path(__file__).resolve().parents[1] / "tools" / "build_handoff.py"
    shutil.copyfile(builder, root / "tools" / builder.name)
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("print('hello')\n")
    for name in [".env", ".env.example", "app/.env", "app/private.db", "app/private.pem"]:
        (root / name).write_text("PRIVATE_SENTINEL")
    (root / "app" / "linked.py").symlink_to(root / ".env")
    (root / "app" / "linked_directory").symlink_to(root / "tools", target_is_directory=True)
    (root / "handoff/secrets").mkdir(parents=True)
    (root / "handoff/secrets/secret.py").write_text("PRIVATE_SENTINEL")
    output = tmp_path / "source.zip"
    command = [sys.executable, str(root / "tools" / builder.name), "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True)
    original = output.read_bytes()
    subprocess.run(command, check=True, capture_output=True)
    assert output.read_bytes() == original
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "tggoals/.env.example", "tggoals/app/main.py", "tggoals/tools/build_handoff.py"
        }
        assert all(b"PRIVATE_SENTINEL" not in archive.read(n) for n in archive.namelist())
        archive.extractall(tmp_path / "unpacked")
    extracted = tmp_path / "unpacked" / "tggoals"
    rebuilt = tmp_path / "rebuilt.zip"
    assert not (extracted / ".git").exists()
    subprocess.run([sys.executable, str(extracted / "tools" / builder.name),
                    "--output", str(rebuilt)], check=True, capture_output=True)
    assert rebuilt.read_bytes() == original
