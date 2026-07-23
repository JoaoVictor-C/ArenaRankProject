output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "redis_primary_endpoint" {
  value = module.elasticache.primary_endpoint
}

output "archive_bucket" {
  value = module.s3.bucket_name
}

output "api_irsa_role_arn" {
  value = module.iam.api_role_arn
}

output "worker_irsa_role_arn" {
  value = module.iam.worker_role_arn
}
