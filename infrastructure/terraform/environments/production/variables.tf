variable "region" {
  type    = string
  default = "us-east-1"
}

variable "account_id" {
  type        = string
  description = "AWS account id (used to make the S3 bucket name globally unique)."
}

variable "rds_master_password" {
  type        = string
  sensitive   = true
  description = "RDS master password. Provide via TF_VAR_rds_master_password (CI secret); never commit."
}

variable "redis_auth_token" {
  type        = string
  sensitive   = true
  description = "ElastiCache auth token (transit encryption). Provide via TF_VAR."
}
