from io import BytesIO
from typing import Optional

import aiohttp
from app.settings.my_config import get_settings
from app.utility.my_logger import my_logger
from miniopy_async import Minio

# from miniopy_async.datatypes import ListObjects, Object
from miniopy_async.helpers import ObjectWriteResult

settings = get_settings()

minio_client: Minio = Minio(access_key=settings.MINIO_ROOT_USER, secret_key=settings.MINIO_ROOT_PASSWORD, endpoint=settings.MINIO_ENDPOINT, secure=False)


async def get_object_from_minio(object_name: str) -> bytes:
    try:
        async with aiohttp.ClientSession() as session:
            return await (await minio_client.get_object(bucket_name=settings.MINIO_BUCKET_NAME, object_name=object_name, session=session)).read()
    except Exception as e:
        print(f"Exception in get_data_from_minio: {e}")
        raise ValueError("Exception in get_data_from_minio: {e}")


async def put_object_to_minio(object_name: str, data_stream: BytesIO, length: int, old_object_name: Optional[str] = None, for_update=False) -> str:
    try:
        if for_update and old_object_name:
            await minio_client.remove_object(bucket_name=settings.MINIO_BUCKET_NAME, object_name=old_object_name)

        result: ObjectWriteResult = await minio_client.put_object(bucket_name=settings.MINIO_BUCKET_NAME, object_name=object_name, data=data_stream, length=length)

        return result.object_name
    except Exception as e:
        print(f"Exception in put_data_to_minio: {e}")
        raise ValueError(f"Exception in put_data_to_minio: {e}")


async def remove_object_from_minio(object_name: str) -> None:
    try:
        await minio_client.remove_object(bucket_name=settings.MINIO_BUCKET_NAME, object_name=object_name)
    except Exception as e:
        print(f"Exception in remove_object_from_minio: {e}")


async def wipe_objects_from_minio(user_id: str) -> None:
    try:
        list_objects = await minio_client.list_objects(bucket_name=settings.MINIO_BUCKET_NAME, prefix=f"users/{user_id}/", recursive=True)
        for object in list_objects:
            await remove_object_from_minio(object_name=f"{object.object_name}")
    except Exception as e:
        print(f"Exception in wipe_objects_from_minio: {e}")
        raise ValueError(f"Exception in wipe_objects_from_minio: {e}")


async def minio_ready() -> bool:
    try:
        if not await minio_client.bucket_exists(bucket_name=get_settings().MINIO_BUCKET_NAME):
            await minio_client.make_bucket(bucket_name=get_settings().MINIO_BUCKET_NAME)
        return True
    except Exception as e:
        print(f"🌋 Failed in check_if_bucket_exists: {e}")
        return False


'''
import aioboto3
from botocore.exceptions import ClientError

boto_session = aioboto3.Session(aws_access_key_id=settings.MINIO_ROOT_USER, aws_secret_access_key=settings.MINIO_ROOT_PASSWORD, region_name="us-east-1")


async def minio_ready() -> bool:
    """Check if a bucket exists in MinIO and create it if it doesn't exist."""
    bucket_name = settings.MINIO_BUCKET_NAME
    try:
        async with boto_session.client(service_name="s3", endpoint_url=settings.MINIO_ENDPOINT) as s3:
            # Check if the bucket exists
            try:
                await s3.head_bucket(Bucket=bucket_name)  # This checks if the bucket exists
                print(f"✅ Bucket '{bucket_name}' already exists.")
                return True
            except Exception as e:
                print(f"⚠️ Bucket '{bucket_name}' does not exist. Creating it... {e}")

            # Create the bucket
            await s3.create_bucket(Bucket=bucket_name)
            print(f"✅ Bucket '{bucket_name}' created successfully.")
            return True
    except Exception as e:
        print(f"🌋 Failed to check or create bucket: {e}")
        return False


async def upload_data_to_minio(object_name: str, file_data: bytes) -> bool:
    """Uploads a data to MinIO."""
    try:
        async with boto_session.client(service_name="s3", endpoint_url=settings.MINIO_ENDPOINT) as s3:
            await s3.put_object(Bucket=settings.MINIO_BUCKET_NAME, Key=object_name, Body=file_data)
            return True
    except ClientError as e:
        print(f"Upload failed: {e}")
        return False


async def upload_file_to_minio(object_name: str, file_path: str):
    """Uploads a file to MinIO."""
    try:
        async with boto_session.client(service_name="s3", endpoint_url=settings.MINIO_ENDPOINT) as s3:
            await s3.upload_file(Filename=file_path, Bucket=settings.MINIO_BUCKET_NAME, Key=object_name)
            return True
    except ClientError as e:
        print(f"Upload failed: {e}")
        return False


async def get_data_from_minio(object_name: str) -> Optional[bytes]:
    """Downloads a file from MinIO."""
    try:
        async with boto_session.client(service_name="s3", endpoint_url=settings.MINIO_ENDPOINT) as s3:
            response = await s3.get_object(Bucket=settings.MINIO_BUCKET_NAME, Key=object_name)
            return await response["Body"].read()
    except ClientError as e:
        print(f"Download failed: {e}")
        return None


async def delete_from_minio(object_name: str) -> bool:
    """Deletes a file from MinIO."""
    try:
        async with boto_session.client(service_name="s3", endpoint_url=settings.MINIO_ENDPOINT) as s3:
            await s3.delete_object(Bucket=settings.MINIO_BUCKET_NAME, Key=object_name)
            return True
    except ClientError as e:
        print(f"Delete failed: {e}")
        return False

'''
