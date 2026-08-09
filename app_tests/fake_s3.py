"""
Minimal in-memory fake mimicking the small slice of the boto3 S3 client
API lib/blob_storage.py actually uses (download_file, upload_file,
get_paginator("list_objects_v2")). Lets tests exercise the real
fetch/cache/list logic without real B2/network access.
"""


class ClientError(Exception):
    """Mirrors botocore.exceptions.ClientError's .response shape closely
    enough for blob_storage.py's error-code check to work against it."""
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class FakePaginator:
    def __init__(self, objects):
        self._objects = objects

    def paginate(self, Bucket, Prefix, Delimiter):
        prefixes = set()
        for key in self._objects:
            if not key.startswith(Prefix):
                continue
            rest = key[len(Prefix):]
            if Delimiter in rest:
                prefixes.add(Prefix + rest.split(Delimiter)[0] + Delimiter)
        yield {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)]}


class FakeS3Client:
    def __init__(self):
        self.objects = {}  # object_key -> bytes
        self.download_calls = []  # for asserting caching actually avoids re-downloads

    def put(self, key, data):
        self.objects[key] = data if isinstance(data, bytes) else data.encode()

    def download_file(self, Bucket, Key, Filename):
        self.download_calls.append(Key)
        if Key not in self.objects:
            raise ClientError("404")
        with open(Filename, "wb") as f:
            f.write(self.objects[Key])

    def upload_file(self, Filename, Bucket, Key):
        with open(Filename, "rb") as f:
            self.objects[Key] = f.read()

    def get_paginator(self, operation_name):
        assert operation_name == "list_objects_v2"
        return FakePaginator(self.objects)