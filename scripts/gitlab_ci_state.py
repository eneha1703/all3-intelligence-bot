"""Small GitLab CI helpers for the temporary SQLite state bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


TABLES_TO_COUNT = (
    "sources",
    "pipeline_runs",
    "raw_items",
    "normalized_items",
    "radar_decisions",
    "canonical_events",
    "event_members",
    "telegram_deliveries",
    "telegram_group_messages",
    "telegram_group_message_links",
    "telegram_reaction_picks",
    "weekly_digest_runs",
    "weekly_digest_candidates",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    try:
        counts: dict[str, int] = {}
        for table_name in TABLES_TO_COUNT:
            try:
                counts[table_name] = int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
            except sqlite3.Error:
                counts[table_name] = -1
        return counts
    finally:
        connection.close()


def _integrity_check(database_path: Path) -> str:
    connection = sqlite3.connect(database_path)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def _gitlab_project_api_url(api_url: str, project_id: str) -> str:
    return f"{api_url.rstrip('/')}/projects/{quote(str(project_id), safe='')}"


def _gitlab_auth_headers(job_token: str) -> dict[str, str]:
    return {"JOB-TOKEN": job_token}


def _request_bytes(url: str, job_token: str, *, method: str = "GET", data: bytes | None = None) -> bytes:
    headers = _gitlab_auth_headers(job_token)
    if data is not None:
        headers["Content-Type"] = "application/zip"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=120) as response:
            return response.read()
    except HTTPError:
        raise
    except URLError as exc:
        raise SystemExit(f"GitLab state package request failed: {exc}") from exc


def _generic_package_url(
    *,
    api_url: str,
    project_id: str,
    package_name: str,
    package_version: str,
    package_file: str,
) -> str:
    project_url = _gitlab_project_api_url(api_url, project_id)
    return (
        f"{project_url}/packages/generic/"
        f"{quote(package_name, safe='')}/"
        f"{quote(package_version, safe='')}/"
        f"{quote(package_file, safe='')}"
    )


def _list_gitlab_state_package_versions(
    *,
    api_url: str,
    project_id: str,
    package_name: str,
    job_token: str,
) -> list[str]:
    project_url = _gitlab_project_api_url(api_url, project_id)
    url = (
        f"{project_url}/packages"
        f"?package_type=generic&package_name={quote(package_name, safe='')}"
        "&order_by=created_at&sort=desc&per_page=20"
    )
    try:
        payload = _request_bytes(url, job_token)
    except HTTPError as exc:
        raise SystemExit(f"Cannot list GitLab state packages: HTTP {exc.code}") from exc
    packages = json.loads(payload.decode("utf-8"))
    versions: list[str] = []
    for package in packages:
        version = package.get("version")
        if isinstance(version, str) and version:
            versions.append(version)
    return versions


def _extract_database_from_zip(zip_path: Path, database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temp_database_path = database_path.with_suffix(f"{database_path.suffix}.tmp")
    with zipfile.ZipFile(zip_path) as archive:
        member_name = next(
            (name for name in archive.namelist() if Path(name).name == "all3_radar.db"),
            None,
        )
        if not member_name:
            raise SystemExit(f"State zip does not contain all3_radar.db: {zip_path}")
        with archive.open(member_name) as source, temp_database_path.open("wb") as target:
            target.write(source.read())
    integrity = _integrity_check(temp_database_path)
    if integrity != "ok":
        temp_database_path.unlink(missing_ok=True)
        raise SystemExit(f"Downloaded state DB failed integrity_check: {integrity}")
    temp_database_path.replace(database_path)


def _restore_state_from_gitlab_package(
    *,
    api_url: str | None,
    project_id: str | None,
    package_name: str | None,
    package_file: str | None,
    job_token: str | None,
    database_path: Path,
) -> bool:
    if not all((api_url, project_id, package_name, package_file, job_token)):
        return False

    versions = _list_gitlab_state_package_versions(
        api_url=str(api_url),
        project_id=str(project_id),
        package_name=str(package_name),
        job_token=str(job_token),
    )
    if not versions:
        print(f"No GitLab state package found for package={package_name}; falling back to cache/seed.")
        return False

    for version in versions:
        url = _generic_package_url(
            api_url=str(api_url),
            project_id=str(project_id),
            package_name=str(package_name),
            package_version=version,
            package_file=str(package_file),
        )
        try:
            payload = _request_bytes(url, str(job_token))
        except HTTPError as exc:
            if exc.code == 404:
                print(f"GitLab state package version={version} has no {package_file}; trying older state.")
                continue
            raise SystemExit(f"Cannot download GitLab state package version={version}: HTTP {exc.code}") from exc

        download_path = database_path.with_suffix(".state-package.zip")
        download_path.parent.mkdir(parents=True, exist_ok=True)
        download_path.write_bytes(payload)
        _extract_database_from_zip(download_path, database_path)
        download_path.unlink(missing_ok=True)
        print(f"Restored state DB from GitLab package: package={package_name} version={version}")
        print(f"database={database_path} size={database_path.stat().st_size} sha256={_sha256(database_path)}")
        return True

    print(f"No downloadable GitLab state package file found for package={package_name}; falling back to cache/seed.")
    return False


def restore_state(
    seed_zip: Path,
    database_path: Path,
    *,
    gitlab_api_url: str | None = None,
    gitlab_project_id: str | None = None,
    gitlab_package_name: str | None = None,
    gitlab_package_file: str | None = None,
    gitlab_job_token: str | None = None,
) -> None:
    if _restore_state_from_gitlab_package(
        api_url=gitlab_api_url,
        project_id=gitlab_project_id,
        package_name=gitlab_package_name,
        package_file=gitlab_package_file,
        job_token=gitlab_job_token,
        database_path=database_path,
    ):
        return

    remote_state_configured = all(
        (gitlab_api_url, gitlab_project_id, gitlab_package_name, gitlab_package_file, gitlab_job_token)
    )
    if remote_state_configured and seed_zip.exists():
        _extract_database_from_zip(seed_zip, database_path)
        print(f"Restored state DB from seed after missing remote package: {seed_zip}")
        print(f"database={database_path} size={database_path.stat().st_size} sha256={_sha256(database_path)}")
        return

    if database_path.exists():
        print(f"State DB already present: {database_path} ({database_path.stat().st_size} bytes)")
        print(f"sha256={_sha256(database_path)}")
        return

    if not seed_zip.exists():
        raise SystemExit(f"State DB is missing and seed zip does not exist: {seed_zip}")

    _extract_database_from_zip(seed_zip, database_path)

    print(f"Restored state DB from seed: {seed_zip}")
    print(f"database={database_path} size={database_path.stat().st_size} sha256={_sha256(database_path)}")


def _upload_state_package(
    *,
    zip_path: Path,
    api_url: str | None,
    project_id: str | None,
    package_name: str | None,
    package_version: str | None,
    package_file: str | None,
    job_token: str | None,
) -> None:
    if not all((api_url, project_id, package_name, package_version, package_file, job_token)):
        return
    url = _generic_package_url(
        api_url=str(api_url),
        project_id=str(project_id),
        package_name=str(package_name),
        package_version=str(package_version),
        package_file=str(package_file),
    )
    try:
        _request_bytes(url, str(job_token), method="PUT", data=zip_path.read_bytes())
    except HTTPError as exc:
        if exc.code in {400, 409}:
            print(
                "State package upload was not accepted, probably because this job version already exists: "
                f"HTTP {exc.code}"
            )
            return
        raise SystemExit(f"Cannot upload GitLab state package: HTTP {exc.code}") from exc
    print(f"Uploaded state package: package={package_name} version={package_version} file={package_file}")


def write_snapshot(
    database_path: Path,
    output_dir: Path,
    label: str,
    *,
    gitlab_api_url: str | None = None,
    gitlab_project_id: str | None = None,
    gitlab_package_name: str | None = None,
    gitlab_package_version: str | None = None,
    gitlab_package_file: str | None = None,
    gitlab_job_token: str | None = None,
) -> None:
    if not database_path.exists():
        raise SystemExit(f"Cannot snapshot missing database: {database_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_path": str(database_path),
        "file_size_bytes": database_path.stat().st_size,
        "sha256": _sha256(database_path),
        "integrity_check": _integrity_check(database_path),
        "table_rows": _table_counts(database_path),
    }
    manifest_path = output_dir / f"{label}-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    zip_path = output_dir / f"{label}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(database_path, "all3_radar.db")
        archive.write(manifest_path, manifest_path.name)

    print(f"Wrote state snapshot: {zip_path}")
    print(f"manifest={manifest_path}")
    _upload_state_package(
        zip_path=zip_path,
        api_url=gitlab_api_url,
        project_id=gitlab_project_id,
        package_name=gitlab_package_name,
        package_version=gitlab_package_version,
        package_file=gitlab_package_file,
        job_token=gitlab_job_token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="GitLab CI state helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore_parser = subparsers.add_parser("restore", help="Restore DB from seed when cache is empty")
    restore_parser.add_argument("--seed-zip", required=True, type=Path)
    restore_parser.add_argument("--database", required=True, type=Path)
    restore_parser.add_argument("--gitlab-api-url")
    restore_parser.add_argument("--gitlab-project-id")
    restore_parser.add_argument("--gitlab-package-name")
    restore_parser.add_argument("--gitlab-package-file")
    restore_parser.add_argument("--gitlab-job-token")

    snapshot_parser = subparsers.add_parser("snapshot", help="Write a compressed DB snapshot artifact")
    snapshot_parser.add_argument("--database", required=True, type=Path)
    snapshot_parser.add_argument("--output-dir", required=True, type=Path)
    snapshot_parser.add_argument("--label", required=True)
    snapshot_parser.add_argument("--gitlab-api-url")
    snapshot_parser.add_argument("--gitlab-project-id")
    snapshot_parser.add_argument("--gitlab-package-name")
    snapshot_parser.add_argument("--gitlab-package-version")
    snapshot_parser.add_argument("--gitlab-package-file")
    snapshot_parser.add_argument("--gitlab-job-token")

    args = parser.parse_args()
    if args.command == "restore":
        restore_state(
            args.seed_zip,
            args.database,
            gitlab_api_url=args.gitlab_api_url,
            gitlab_project_id=args.gitlab_project_id,
            gitlab_package_name=args.gitlab_package_name,
            gitlab_package_file=args.gitlab_package_file,
            gitlab_job_token=args.gitlab_job_token,
        )
    elif args.command == "snapshot":
        write_snapshot(
            args.database,
            args.output_dir,
            args.label,
            gitlab_api_url=args.gitlab_api_url,
            gitlab_project_id=args.gitlab_project_id,
            gitlab_package_name=args.gitlab_package_name,
            gitlab_package_version=args.gitlab_package_version,
            gitlab_package_file=args.gitlab_package_file,
            gitlab_job_token=args.gitlab_job_token,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
