from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_hourly_runner_uses_safe_send_monitoring_with_existing_exclusive_lock() -> None:
    runner = (PROJECT_ROOT / "scripts" / "run-hourly-collection.ps1").read_text(
        encoding="utf-8"
    )

    assert "monitor-gpus --send --quiet" in runner
    assert "--reference-bootstrap" not in runner
    assert "hourly-collection.lock" in runner
    assert "FileMode]::CreateNew" in runner
    assert "msg.exe" in runner
    assert "Send-MonitoringFailureNotice -Message" in runner
    assert "collect-gpus --quiet" not in runner


def test_registration_preserves_the_existing_task_name_and_runner_path() -> None:
    registration = (PROJECT_ROOT / "scripts" / "register-hourly-collection.ps1").read_text(
        encoding="utf-8"
    )

    assert '"DealWatchPL-HourlyCollection"' in registration
    assert '"run-hourly-collection.ps1"' in registration
    assert "[Environment]::SystemDirectory" in registration
