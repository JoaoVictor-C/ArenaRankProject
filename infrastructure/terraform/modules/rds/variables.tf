variable "name" {
  type        = string
  description = "Name prefix."
}

variable "vpc_id" {
  type        = string
  description = "VPC id for the DB security group."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for the DB subnet group."
}

variable "allowed_security_group_id" {
  type        = string
  description = "Security group allowed to reach Postgres (EKS cluster SG)."
}

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "replica_instance_class" {
  type    = string
  default = ""
}

variable "allocated_storage" {
  type    = number
  default = 100
}

variable "max_allocated_storage" {
  type    = number
  default = 1000
}

variable "database_name" {
  type    = string
  default = "arena"
}

variable "master_username" {
  type    = string
  default = "arena"
}

variable "master_password" {
  type        = string
  sensitive   = true
  description = "Master password (inject from Secrets Manager / TF_VAR, never commit)."
}

variable "multi_az" {
  type    = bool
  default = true
}

variable "backup_retention_period" {
  type    = number
  default = 30
}

variable "create_read_replica" {
  type    = bool
  default = true
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  type    = bool
  default = false
}

variable "apply_immediately" {
  type    = bool
  default = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
