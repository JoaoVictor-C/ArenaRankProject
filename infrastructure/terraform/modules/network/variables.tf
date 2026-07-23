variable "name" {
  description = "Name prefix for network resources."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name (for subnet discovery tags)."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of AZs to spread subnets across."
  type        = number
  default     = 3
}

variable "single_nat_gateway" {
  description = "Use one shared NAT gateway (cheaper, non-HA) instead of one per AZ."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
