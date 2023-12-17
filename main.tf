terraform {
  required_providers {
    yandex = {
      source = "yandex-cloud/yandex"
    }
  }
  required_version = ">= 0.13"
}

provider "yandex" {
  service_account_key_file = var.service_account_key_file
  cloud_id                 = var.cloud_id
  folder_id                = var.folder_id
  zone                     = var.zone
}

// Создание сервисного аккаунта
resource "yandex_iam_service_account" "photos-sa" {
  name = "photos-sa-vvot21"
}

// Назначение роли сервисному аккаунту для возможности управлениями ресурсами
resource "yandex_resourcemanager_folder_iam_member" "photos-sa-editor" {
  folder_id = var.folder_id
  role      = "editor"
  member    = "serviceAccount:${yandex_iam_service_account.photos-sa.id}"
}

// Назначение роли сервисному аккаунту для доступа к бакетам
resource "yandex_resourcemanager_folder_iam_member" "photos-sa-storage-editor" {
  folder_id = var.folder_id
  role      = "storage.editor"
  member    = "serviceAccount:${yandex_iam_service_account.photos-sa.id}"
}

// Назначение роли сервисному аккаунту для запуска функций
resource "yandex_resourcemanager_folder_iam_member" "photos-sa-function-invoker" {
  folder_id = var.folder_id
  role      = "functions.functionInvoker"
  member    = "serviceAccount:${yandex_iam_service_account.photos-sa.id}"
}

// Назначение роли сервисному аккаунту для работы с Yandex Vision
resource "yandex_resourcemanager_folder_iam_member" "photos-sa-vision-user" {
  folder_id = var.folder_id
  role      = "ai.vision.user"
  member    = "serviceAccount:${yandex_iam_service_account.photos-sa.id}"
}

// Создание статического ключа доступа
resource "yandex_iam_service_account_static_access_key" "photos-sa-static-key" {
  service_account_id = yandex_iam_service_account.photos-sa.id
  description        = "Static access key"
}

// Создание бакета для загрузки оригинальных фотографий
resource "yandex_storage_bucket" "photos-bucket" {
  access_key = yandex_iam_service_account_static_access_key.photos-sa-static-key.access_key
  secret_key = yandex_iam_service_account_static_access_key.photos-sa-static-key.secret_key
  bucket     = "vvot21-photos"
}

// Создание бакета для загрузки фотографий лиц
resource "yandex_storage_bucket" "faces-bucket" {
  access_key = yandex_iam_service_account_static_access_key.photos-sa-static-key.access_key
  secret_key = yandex_iam_service_account_static_access_key.photos-sa-static-key.secret_key
  bucket     = "vvot21-faces"
}

// Создание очереди для заданий на создание фотографии лица
resource "yandex_message_queue" "task-queue" {
  access_key = yandex_iam_service_account_static_access_key.photos-sa-static-key.access_key
  secret_key = yandex_iam_service_account_static_access_key.photos-sa-static-key.secret_key
  name       = "vvot21-task"
}

// Архивирование кода для определения лиц
resource "archive_file" "face-detection-zip" {
  output_path = "face_detection.zip"
  type        = "zip"
  source_dir  = "face_detection"
}

// Создание функции для определения лиц
resource "yandex_function" "face-detection" {
  name               = "vvot21-face-detection"
  description        = "Function for face detection"
  user_hash          = "8"
  runtime            = "python311"
  entrypoint         = "face_detection.handler"
  memory             = var.function_memory
  execution_timeout  = var.function_execution_timeout
  service_account_id = yandex_iam_service_account.photos-sa.id
  content {
    zip_filename = "face_detection.zip"
  }
  environment = {
    ACCESS_KEY = yandex_iam_service_account_static_access_key.photos-sa-static-key.access_key
    SECRET_KEY = yandex_iam_service_account_static_access_key.photos-sa-static-key.secret_key
    QUEUE_URL  = yandex_message_queue.task-queue.id
  }
}

// Создание триггера, срабатывающего при загрузке фотографии в бакет и запускающего функцию определения лиц
resource "yandex_function_trigger" "photo-trigger" {
  name        = "vvot21-photo"
  description = "Trigger for photos bucket to face detection function"
  object_storage {
    bucket_id    = yandex_storage_bucket.photos-bucket.id
    create       = true
    suffix       = ".jpg"
    batch_cutoff = var.trigger_batch_cutoff
  }
  function {
    id                 = yandex_function.face-detection.id
    service_account_id = yandex_iam_service_account.photos-sa.id
  }
}

// Создание базы данных
resource "yandex_ydb_database_serverless" "database" {
  name      = "vvot21-db-photo-face"
  folder_id = var.folder_id
  serverless_database {
    storage_size_limit = var.storage_size_limit
  }
}

// Создание таблицы в базе данных для хранения информации о фотографиях
resource "yandex_ydb_table" "photos_table" {
  path              = "photos"
  connection_string = yandex_ydb_database_serverless.database.ydb_full_endpoint
  column {
    name     = "photo"
    type     = "Utf8"
    not_null = true
  }
  column {
    name     = "original_photo"
    type     = "Utf8"
    not_null = true
  }
  column {
    name     = "name"
    type     = "Utf8"
    not_null = false
  }
  primary_key = ["photo"]
}

// Создание таблицы в базе данных для хранения информации об отправленных сообщениях
resource "yandex_ydb_table" "messages_table" {
  path              = "messages"
  connection_string = yandex_ydb_database_serverless.database.ydb_full_endpoint
  column {
    name     = "chat_id"
    type     = "Int32"
    not_null = true
  }
  column {
    name     = "message_id"
    type     = "Int32"
    not_null = true
  }
  column {
    name     = "photo"
    type     = "Utf8"
    not_null = true
  }
  primary_key = ["chat_id", "message_id"]
}

// Архивирование кода для вырезания фотографий лиц
resource "archive_file" "face-cut-zip" {
  output_path = "face_cut.zip"
  type        = "zip"
  source_dir  = "face_cut"
}

// Создание функции для вырезания фотографий лиц
resource "yandex_function" "face-cut" {
  name               = "vvot21-face-cut"
  description        = "Function for face cut"
  user_hash          = "3"
  runtime            = "python311"
  entrypoint         = "face_cut.handler"
  memory             = var.function_memory
  execution_timeout  = var.function_execution_timeout
  service_account_id = yandex_iam_service_account.photos-sa.id
  content {
    zip_filename = "face_cut.zip"
  }
  environment = {
    ACCESS_KEY        = yandex_iam_service_account_static_access_key.photos-sa-static-key.access_key
    SECRET_KEY        = yandex_iam_service_account_static_access_key.photos-sa-static-key.secret_key
    DATABASE_ENDPOINT = yandex_ydb_database_serverless.database.ydb_full_endpoint
  }
}

// Создание триггера, разгружающего очередь и запускающего функцию для вырезания фотографий лиц
resource "yandex_function_trigger" "task-trigger" {
  name        = "vvot21-task"
  description = "Trigger for task to face cut function"
  message_queue {
    queue_id           = yandex_message_queue.task-queue.arn
    service_account_id = yandex_iam_service_account.photos-sa.id
    batch_cutoff       = var.trigger_batch_cutoff
    batch_size         = 1
  }
  function {
    id                 = yandex_function.face-cut.id
    service_account_id = yandex_iam_service_account.photos-sa.id
  }
}

// Создание API Gateway
resource "yandex_api_gateway" "api-gateway" {
  name        = "vvot21-apigw"
  description = "API Gateway for photos"
  spec        = <<-EOT
openapi: 3.0.0
info:
  title: Face photos API
  version: 1.0.0
paths:
  /:
    get:
      summary: Get face photos from Yandex Cloud Object Storage
      parameters:
        - name: face
          in: query
          required: true
          schema:
            type: string
      x-yc-apigateway-integration:
        type: object_storage
        bucket: vvot21-faces
        object: '{face}'
        service_account_id: ${yandex_iam_service_account.photos-sa.id}
  /original:
    get:
      summary: Get original photos from Yandex Cloud Object Storage
      parameters:
        - name: photo
          in: query
          required: true
          schema:
            type: string
      x-yc-apigateway-integration:
        type: object_storage
        bucket: vvot21-photos
        object: '{photo}'
        service_account_id: ${yandex_iam_service_account.photos-sa.id}
EOT
}

// Архивирование кода для бота
resource "archive_file" "bot-zip" {
  output_path = "bot.zip"
  type        = "zip"
  source_dir  = "bot"
}

// Создание функции для бота
resource "yandex_function" "bot" {
  name               = "vvot21-bot"
  description        = "Function for bot"
  user_hash          = "5"
  runtime            = "python311"
  entrypoint         = "bot.handler"
  memory             = var.function_memory
  execution_timeout  = var.function_execution_timeout
  service_account_id = yandex_iam_service_account.photos-sa.id
  content {
    zip_filename = "bot.zip"
  }
  environment = {
    TGKEY             = var.tg_key
    DATABASE_ENDPOINT = yandex_ydb_database_serverless.database.ydb_full_endpoint
    API_GATEWAY_ID    = yandex_api_gateway.api-gateway.id
  }
}

// Включение публичного доступа функции бота
resource "yandex_function_iam_binding" "bot-iam" {
  function_id = yandex_function.bot.id
  role        = "serverless.functions.invoker"
  members = [
    "system:allUsers",
  ]
}

// Регистрация вебхука
data "http" "webhook" {
  url = "https://api.telegram.org/bot${var.tg_key}/setWebhook?url=https://functions.yandexcloud.net/${yandex_function.bot.id}"
}

