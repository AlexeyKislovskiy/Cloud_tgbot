variable "service_account_key_file" {
  type        = string
  description = "Key file name"
}

variable "cloud_id" {
  type        = string
  description = "Cloud id"
}

variable "folder_id" {
  type        = string
  description = "Folder id"
}

variable "zone" {
  type        = string
  description = "Zone"
}

variable "tg_key" {
  type        = string
  description = "Telegram Bot API Key"
}

variable "function_memory" {
  type        = number
  description = "Function memory"
}

variable "function_execution_timeout" {
  type        = number
  description = "Function execution timeout"
}

variable "trigger_batch_cutoff" {
  type        = number
  description = "Trigger batch cutoff"
}

variable "storage_size_limit" {
  type        = number
  description = "Yandex database size limit in GB"
}