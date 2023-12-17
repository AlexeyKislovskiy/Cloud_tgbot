import os
import boto3
import base64
import requests
import json

def get_boto_session():
    access_key = os.environ["ACCESS_KEY"]
    secret_key = os.environ["SECRET_KEY"]
    boto_session = boto3.session.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    return boto_session

def get_storage_client():
    return get_boto_session().client(
        service_name='s3',
        endpoint_url='https://storage.yandexcloud.net',
        region_name='ru-central1'
    )

def get_queue_client():
    return get_boto_session().client(
        service_name='sqs',
        endpoint_url='https://message-queue.api.cloud.yandex.net',
        region_name='ru-central1'
    )

def handler(event, context):
    s3 = get_storage_client()
    details = event["messages"][0]["details"]
    bucket_id = details["bucket_id"]
    object_id = details["object_id"]
    folder_id = event["messages"][0]["event_metadata"]["folder_id"]
    photo_object = s3.get_object(Bucket=bucket_id, Key=object_id)
    photo = photo_object['Body'].read()
    content = base64.b64encode(photo).decode('utf-8')
    body_json = {
        "folderId": folder_id,
        "analyze_specs": [
            {
                "content": content,
                "features": [{"type": "FACE_DETECTION"}]
            }
        ]
    }
    url = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
    headers = {
        "Authorization": f"Bearer {context.token['access_token']}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, json=body_json, headers=headers)
    faces = response.json()["results"][0]["results"][0]["faceDetection"]["faces"]
    queue_url = os.environ["QUEUE_URL"]
    sqs = get_queue_client()
    for face in faces:
        coordinates = face["boundingBox"]["vertices"]
        task = f"{bucket_id};{object_id}"
        for coordinate in coordinates:
            task += f";{coordinate['x']};{coordinate['y']}"
        sqs.send_message(QueueUrl=queue_url, MessageBody=task)

    return {'statusCode': 200}