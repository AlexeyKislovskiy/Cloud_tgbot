import os
import requests
import json
import ydb
import ydb.iam

endpoint = os.environ["DATABASE_ENDPOINT"].split("/?database=")[0]
database = os.environ["DATABASE_ENDPOINT"].split("/?database=")[1]
driver = ydb.Driver(endpoint=endpoint, database=database, credentials=ydb.iam.MetadataUrlCredentials())
driver.wait(fail_fast=True, timeout=5)
pool = ydb.SessionPool(driver)

def get_face_without_name(pool):
    def selectit(session):
        query = "SELECT photo FROM photos WHERE name IS NULL LIMIT 1"      
        return session.transaction().execute(query, commit_tx=True)
    result_set = pool.retry_operation_sync(selectit)
    if not result_set[0].rows:
        return None
    else:
        return result_set[0].rows[0].photo 

def save_message_to_database(pool, chat_id, message_id, photo):
    def insertit(session):
        query = """
        DECLARE $chat_id AS Int32;
        DECLARE $message_id AS Int32;
        DECLARE $photo AS Utf8;
        INSERT INTO messages (chat_id, message_id, photo) VALUES ($chat_id, $message_id, $photo);
        """      
        prepare_query = session.prepare(query)
        session.transaction().execute(prepare_query, {'$chat_id': chat_id, '$message_id': message_id, '$photo': str.encode(photo)}, commit_tx=True)
    pool.retry_operation_sync(insertit)

def get_photo_by_message(pool, chat_id, message_id):
    def selectit(session):
        query = """
        DECLARE $chat_id AS Int32;
        DECLARE $message_id AS Int32;
        SELECT photo FROM messages WHERE chat_id = $chat_id AND message_id = $message_id;
        """      
        prepare_query = session.prepare(query)
        return session.transaction().execute(prepare_query, {'$chat_id': chat_id, '$message_id': message_id}, commit_tx=True)
    result_set = pool.retry_operation_sync(selectit)
    if not result_set[0].rows:
        return None
    else:
        return result_set[0].rows[0].photo

def check_photo_without_name(pool, photo):
    def selectit(session):
        query = """
        DECLARE $photo AS Utf8;
        SELECT photo FROM photos WHERE name IS NULL AND photo = $photo;
        """      
        prepare_query = session.prepare(query)
        return session.transaction().execute(prepare_query, {'$photo': str.encode(photo)}, commit_tx=True)
    result_set = pool.retry_operation_sync(selectit)
    if not result_set[0].rows:
        return False
    else:
        return True

def get_original_photo(pool, photo):
    def selectit(session):
        query = """
        DECLARE $photo AS Utf8;
        SELECT original_photo FROM photos WHERE photo = $photo;
        """      
        prepare_query = session.prepare(query)
        return session.transaction().execute(prepare_query, {'$photo': str.encode(photo)}, commit_tx=True)
    result_set = pool.retry_operation_sync(selectit)
    return result_set[0].rows[0].original_photo

def set_photo_name(pool, photo, name):
    original_photo = get_original_photo(pool, photo)
    def upsertit(session):
        query = """
        DECLARE $photo AS Utf8;
        DECLARE $original_photo AS Utf8;
        DECLARE $name AS Utf8;
        UPSERT INTO photos (photo, original_photo, name) VALUES ($photo, $original_photo, $name)
        """      
        prepare_query = session.prepare(query)
        session.transaction().execute(prepare_query, {'$photo': str.encode(photo), '$original_photo': str.encode(original_photo), '$name': str.encode(name)}, commit_tx=True)
    pool.retry_operation_sync(upsertit)

def get_all_photos(pool, name):
    def selectit(session):
        query = """
        DECLARE $name AS Utf8;
        SELECT original_photo FROM photos WHERE name = $name;
        """      
        prepare_query = session.prepare(query)
        return session.transaction().execute(prepare_query, {'$name': str.encode(name)}, commit_tx=True)
    result_set = pool.retry_operation_sync(selectit)
    return [d['original_photo'] for d in result_set[0].rows]

def send_message(tgkey, text, chat_id, message_id):
    url = f"https://api.telegram.org/bot{tgkey}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "reply_to_message_id": message_id}
    r = requests.get(url=url, params=params)

def send_error(tgkey, chat_id, message_id):
    send_message(tgkey, "Ошибка", chat_id, message_id)

def handler(event, context):
    tgkey = os.environ["TGKEY"]
    update = json.loads(event["body"])
    if "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        if "text" in message:
            text = message["text"]
            if "reply_to_message" in message:
                reply = message["reply_to_message"]
                reply_id = reply["message_id"]
                photo = get_photo_by_message(pool, chat_id, reply_id)
                if photo is None:
                    send_error(tgkey, chat_id, message_id)
                elif not check_photo_without_name(pool, photo):
                    answer_text = "У этой фотографии уже есть имя"
                    send_message(tgkey, answer_text, chat_id, message_id)
                else:
                    set_photo_name(pool, photo, text)
                    answer_text = f"Данная фотография успешно сохранена в базе с именем {text}"
                    send_message(tgkey, answer_text, chat_id, message_id)
            elif text == "/getface":
                face_id = get_face_without_name(pool)
                if face_id is None:
                    answer_text = "Больше не осталось фотографий без имени"
                    send_message(tgkey, answer_text, chat_id, message_id)
                else:
                    url = f"https://api.telegram.org/bot{tgkey}/sendPhoto"
                    api_gateway_id = os.environ["API_GATEWAY_ID"]
                    face_url = f"https://{api_gateway_id}.apigw.yandexcloud.net/?face={face_id}"
                    params = {"chat_id": chat_id, "photo": face_url}
                    r = requests.get(url=url, params=params)
                    sent_message_id = r.json()["result"]["message_id"]
                    save_message_to_database(pool, chat_id, sent_message_id, face_id)
            elif text.startswith("/find "):
                name = text[len("/find "):]
                original_photos = get_all_photos(pool, name)
                if not original_photos:
                    answer_text = f"Фотографии с именем {name} не найдены"
                    send_message(tgkey, answer_text, chat_id, message_id)
                for original_photo in original_photos:
                    url = f"https://api.telegram.org/bot{tgkey}/sendPhoto"
                    api_gateway_id = os.environ["API_GATEWAY_ID"]
                    photo_url = f"https://{api_gateway_id}.apigw.yandexcloud.net/original/?photo={original_photo}"
                    params = {"chat_id": chat_id, "photo": photo_url}
                    r = requests.get(url=url, params=params)
            else:
                send_error(tgkey, chat_id, message_id)
        else:
            send_error(tgkey, chat_id, message_id)
    
    return {
        'statusCode': 200
    }