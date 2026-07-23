variable "region" {
  type    = string
  default = "us-east-1"
}

variable "account_id" {
  type        = string
  description = "AWS account id (S3 bucket uniqueness)."
}

variable "rds_master_password" {
  type        = string
  sensitive   = true
  description = "RDS master password (TF_VAR / CI secret)."
}
