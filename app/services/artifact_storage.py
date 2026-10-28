import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile


@dataclass
class StagedArtifact:
    temporary_path: Path
    final_path: Path
    sha256: str
    size_bytes: int
    published: bool = False

    def publish(self) -> None:
        # A hard link is atomic and fails if the immutable release path already exists.
        os.link(self.temporary_path, self.final_path)
        self.published = True
        self.temporary_path.unlink()

    def discard(self) -> None:
        self.temporary_path.unlink(missing_ok=True)
        if self.published:
            self.final_path.unlink(missing_ok=True)


class LocalArtifactStorage:
    """Local immutable artifact storage; replaceable by object storage later."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def artifact_path(self, release_id: UUID) -> Path:
        return self.root / f"{release_id}.zip"

    async def stage_upload(
        self,
        upload: UploadFile,
        release_id: UUID,
        max_size_bytes: int,
    ) -> StagedArtifact:
        self.root.mkdir(parents=True, exist_ok=True)
        final_path = self.artifact_path(release_id)
        if final_path.exists():
            raise FileExistsError("Artifact already exists for this release ID")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{release_id}.", suffix=".upload", dir=self.root
        )
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with os.fdopen(descriptor, "wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > max_size_bytes:
                        raise ValueError("Bundle exceeds the configured upload limit")
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

        return StagedArtifact(
            temporary_path=temporary_path,
            final_path=final_path,
            sha256=digest.hexdigest(),
            size_bytes=size_bytes,
        )
