"""Where finished audio and run files live: a local folder, or any S3-compatible bucket (DigitalOcean Spaces)."""

import mimetypes
import shutil
from pathlib import Path


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, local_path: Path, key: str) -> str:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)
        return key

    def put_text(self, text: str, key: str) -> str:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return key

    def get(self, key: str, local_path: Path) -> Path:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.root / key, local_path)
        return local_path

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def url(self, key: str) -> str:
        return f"/files/{key}"


class S3Storage:
    def __init__(self, settings):
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint or None, region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key)

    def put(self, local_path: Path, key: str) -> str:
        content_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
        self.client.upload_file(str(local_path), self.bucket, key, ExtraArgs={"ContentType": content_type})
        return key

    def put_text(self, text: str, key: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=text.encode(), ContentType="application/json")
        return key

    def get(self, key: str, local_path: Path) -> Path:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(local_path))
        return local_path

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError:
            return False

    def url(self, key: str, expires: int = 3600) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires)


def load(settings):
    if settings.storage == "s3":
        return S3Storage(settings)
    if settings.storage == "local":
        return LocalStorage(settings.storage_dir)
    raise ValueError(f"YUE2_STORAGE must be 'local' or 's3', not {settings.storage!r}")
