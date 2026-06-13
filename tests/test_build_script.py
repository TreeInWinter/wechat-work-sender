from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "build.sh"


def _build_script_text() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8")


def test_build_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(BUILD_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_build_script_bootstraps_venv_with_uv():
    script = _build_script_text()

    assert re.search(r"^\s*uv venv\b", script, re.MULTILINE)


def test_build_script_installs_requirements_file():
    script = _build_script_text()

    assert re.search(r"^\s*install_pkg\s+-r\s+requirements\.txt\b", script, re.MULTILINE)


def test_build_script_validates_bundled_donation_asset():
    script = _build_script_text()

    assert 'require_file "assets/donation-wechat.jpg"' in script


def test_build_script_compiles_entrypoint_modules_before_packaging():
    script = _build_script_text()

    assert "-m py_compile" in script
    for module in ("gui_panel.py", "sender.py", "config.py"):
        assert module in script
