from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from app.email.archive import ArchiveNamespace, archive_raw_email


def _archive_root(tmp_path: Path) -> Path:
    root = tmp_path / "raw-email"
    root.mkdir(mode=0o700)
    return root


def test_archive_defaults_to_manual_namespace(tmp_path: Path) -> None:
    root = _archive_root(tmp_path)

    archived = archive_raw_email(b"synthetic email", root)

    assert archived.path.parent.parent == root / "manual"
    assert archived.path.read_bytes() == b"synthetic email"


def test_archive_supports_separate_gmail_namespace(tmp_path: Path) -> None:
    root = _archive_root(tmp_path)
    raw = b"synthetic email"

    manual = archive_raw_email(raw, root)
    gmail = archive_raw_email(raw, root, namespace="gmail")

    assert gmail.sha256 == manual.sha256
    assert gmail.path != manual.path
    assert gmail.path.parent.parent == root / "gmail"
    assert gmail.path.read_bytes() == raw


@pytest.mark.parametrize("namespace", ["", "GMAIL", "../gmail", "other"])
def test_archive_rejects_unknown_namespace(tmp_path: Path, namespace: str) -> None:
    root = _archive_root(tmp_path)

    with pytest.raises(ValueError, match="archive namespace"):
        archive_raw_email(
            b"synthetic email",
            root,
            namespace=cast(ArchiveNamespace, namespace),
        )

    assert not list(root.iterdir())
