from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol

from elyon_api.config import Settings


class StorageBackend(Protocol):
    def open_read(self, path: str) -> BinaryIO: ...
    def write(self, path: str, data: BinaryIO) -> None: ...
    def append(self, path: str, data: bytes) -> None: ...
    def size(self, path: str) -> int: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def move(self, src: str, dst: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _abs(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError("Chemin hors racine de stockage")
        return target

    def open_read(self, path: str) -> BinaryIO:
        return self._abs(path).open("rb")

    def write(self, path: str, data: BinaryIO) -> None:
        target = self._abs(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as out:
            shutil.copyfileobj(data, out)

    def append(self, path: str, data: bytes) -> None:
        target = self._abs(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab") as out:
            out.write(data)

    def size(self, path: str) -> int:
        return self._abs(path).stat().st_size

    def delete(self, path: str) -> None:
        target = self._abs(path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def exists(self, path: str) -> bool:
        return self._abs(path).exists()

    def list(self, prefix: str) -> list[str]:
        base = self._abs(prefix)
        if not base.exists():
            return []
        return [
            str(p.relative_to(self.root.resolve()))
            for p in base.rglob("*")
            if p.is_file()
        ]

    def move(self, src: str, dst: str) -> None:
        shutil.move(str(self._abs(src)), str(self._abs(dst)))


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError("Backend S3 requis : pip install elyon-api[s3]") from exc
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region or None,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
        )

    def open_read(self, path: str) -> BinaryIO:
        import io

        body = self.client.get_object(Bucket=self.bucket, Key=path)["Body"]
        return io.BytesIO(body.read())

    def write(self, path: str, data: BinaryIO) -> None:
        self.client.upload_fileobj(data, self.bucket, path)

    def append(self, path: str, data: bytes) -> None:
        if not self.exists(path):
            self.client.put_object(Bucket=self.bucket, Key=path, Body=data)
        else:
            existing = self.open_read(path).read()
            self.client.put_object(Bucket=self.bucket, Key=path, Body=existing + data)

    def size(self, path: str) -> int:
        return self.client.head_object(Bucket=self.bucket, Key=path)["ContentLength"]

    def delete(self, path: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=path)

    def exists(self, path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=path)
            return True
        except Exception:
            return False

    def list(self, prefix: str) -> list[str]:
        keys = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def move(self, src: str, dst: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket, Key=dst,
            CopySource={"Bucket": self.bucket, "Key": src},
        )
        self.client.delete_object(Bucket=self.bucket, Key=src)


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.media_storage_root)


def safe_storage_path(path: str) -> str:
    norm = os.path.normpath(path)
    if norm.startswith("../") or norm == ".." or norm.startswith("/"):
        raise ValueError("Chemin de stockage invalide")
    return norm