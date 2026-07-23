variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "allowed_security_group_id" {
  type        = string
  description = "EKS cluster SG allowed to reach Redis."
}

variable "engine_version" {
  type    = string
  default = "7.1"
}

variable "node_type" {
  type    = string
  default = "cache.r6g.large"
}

variable "cluster_mode_enabled" {
  type        = bool
  default     = false
  description = "Enable Redis cluster mode (sharded). arq/Redlock prefer disabled."
}

variable "num_shards" {
  type        = number
  default     = 3
  description = "Shards when cluster_mode_enabled (proposal §10.1 target: 3)."
}

variable "replicas_per_shard" {
  type    = number
  default = 1
}

variable "transit_encryption_enabled" {
  type    = bool
  default = true
}

variable "auth_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "snapshot_retention_limit" {
  type    = number
  default = 7
}

variable "apply_immediately" {
  type    = bool
  default = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
