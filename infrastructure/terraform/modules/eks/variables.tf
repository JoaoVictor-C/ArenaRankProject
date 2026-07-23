variable "cluster_name" {
  type        = string
  description = "EKS cluster name."
}

variable "kubernetes_version" {
  type        = string
  description = "EKS Kubernetes minor version."
  default     = "1.30"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for nodes and control-plane ENIs."
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets (control-plane ENIs / ALB)."
}

variable "public_access_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the public API server endpoint."
  default     = ["0.0.0.0/0"]
}

variable "node_instance_types" {
  type        = list(string)
  description = "Instance types for the default managed node group."
  default     = ["m6i.large"]
}

variable "node_capacity_type" {
  type        = string
  description = "ON_DEMAND or SPOT."
  default     = "ON_DEMAND"
}

variable "node_desired_size" {
  type    = number
  default = 3
}

variable "node_min_size" {
  type    = number
  default = 3
}

variable "node_max_size" {
  type    = number
  default = 10
}

variable "tags" {
  type    = map(string)
  default = {}
}
