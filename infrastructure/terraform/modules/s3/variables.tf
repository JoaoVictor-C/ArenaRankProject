variable "bucket_name" {
  type        = string
  description = "Globally-unique bucket name (e.g. arenarank-prod-archives-<acct>)."
}

variable "archive_expiration_days" {
  type        = number
  default     = 1825 # 5 years
  description = "Expire season archives after N days."
}

variable "tags" {
  type    = map(string)
  default = {}
}
