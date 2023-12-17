import os
import boto3
import base64
import requests
import json
import numpy as np
from io import BytesIO
from PIL import Image
import uuid
import io
import ydb
import ydb.iam

endpoint = os.environ["DATABASE_ENDPOINT"].split("/?database=")[0]
database = os.environ["DATABASE_ENDPOINT"].split("/?database=")[1]
driver = ydb.Driver(endpoint=endpoint, database=database, credentials=ydb.iam.MetadataUrlCredentials())
driver.wait(fail_fast=True, timeout=5)
pool = ydb.SessionPool(driver)

def save_to_database(pool, photo, original_photo):
    def insertit(session):
        query = """
        DECLARE $photo AS Utf8;
        DECLARE $original_photo AS Utf8;
        INSERT INTO photos (photo, original_photo) VALUES ($photo, $original_photo);
        """      
        prepare_query = session.prepare(query)
        session.transaction().execute(prepare_query, {'$photo': str.encode(photo), '$original_photo': str.encode(original_photo)}, commit_tx=True)
    pool.retry_operation_sync(insertit)

def get_boto_session():
    access_key = os.environ["ACCESS_KEY"]
    secret_key = os.environ["SECRET_KEY"]
    boto_session = boto3.session.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    return boto_session

def get_storage_client():
    storage_client = get_boto_session().client(
        service_name = 's3',
        endpoint_url = 'https://storage.yandexcloud.net',
        region_name = 'ru-central1'
    )
    return storage_client   

def handler(event, context):
    s3 = get_storage_client()
    messages = event["messages"]
    for message in messages:
        task = message["details"]["message"]["body"]
        task_parts = task.split(";")
        bucket_id = task_parts[0]
        object_id = task_parts[1]
        x1 = int(task_parts[2])
        x2 = int(task_parts[6])
        y1 = int(task_parts[3])
        y2 = int(task_parts[7])
        photo_object = s3.get_object(Bucket = bucket_id, Key = object_id)
        photo_bytes = photo_object['Body'].read()
        photo = np.array(Image.open(BytesIO(photo_bytes)))
        cut_photo = photo[y1:y2, x1:x2]
        cut_photo_image = Image.fromarray(cut_photo)
        img_byte_arr = io.BytesIO()
        cut_photo_image.save(img_byte_arr, format='jpeg')
        img_byte_arr = img_byte_arr.getvalue()
        photo_name = str(uuid.uuid4())
        s3.put_object(Bucket='vvot21-faces', Key=photo_name, Body=img_byte_arr, ContentType='image/jpeg')
        save_to_database(pool, photo_name, object_id)

    return {
        'statusCode': 200
    }