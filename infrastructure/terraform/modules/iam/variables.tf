variable "name" {
  type = string
}

variable "oidc_provider_arn" {
  type        = string
  description = "EKS IRSA OIDC provider ARN."
}

variable "oidc_provider_url" {
  type        = string
  description = "EKS IRSA OIDC provider URL (no scheme)."
}

variable "archive_bucket_arn" {
  type        = string
  description = "S3 archive bucket ARN."
}

variable "ecr_repository_arn" {
  type        = string
  description = "ECR repository ARN (for the GitHub Actions push policy)."
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster name (for the deploy role's eks:DescribeCluster)."
}

variable "create_github_oidc" {
  type        = bool
  default     = true
  description = "Create the GitHub Actions OIDC provider + deploy role."
}

variable "github_repository" {
  type        = string
  default     = "clesioalopes/arenarank-realoficial"
  description = "owner/repo allowed to assume the deploy role."
}

variable "tags" {
  type    = map(string)
  default = {}
}
