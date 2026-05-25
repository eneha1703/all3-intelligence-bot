from pathlib import Path

from all3_radar.app import radar_cli


def test_discover_web_allow_failure_report_writes_report(monkeypatch, tmp_path, capsys) -> None:
    def _raise(*, repo_root: Path, output_dir: Path | None = None):
        raise RuntimeError("provider timed out")

    monkeypatch.setattr(radar_cli, "run_web_discovery", _raise)
    exit_code = radar_cli.main(
        [
            "discover-web",
            "--allow-failure-report",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Web discovery failed but wrote report" in output
    reports = list(tmp_path.glob("web-discovery-failed-*.md"))
    assert len(reports) == 1
    assert "provider timed out" in reports[0].read_text(encoding="utf-8")
