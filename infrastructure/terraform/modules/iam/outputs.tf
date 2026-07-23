output "api_role_arn" {
  value       = aws_iam_role.api.arn
  description = "IRSA role ARN for the api ServiceAccount (api/api)."
}

output "worker_role_arn" {
  value       = aws_iam_role.worker.arn
  description = "IRSA role ARN for the worker ServiceAccount (processing/worker)."
}

output "github_actions_role_arn" {
  value       = var.create_github_oidc ? aws_iam_role.github_actions[0].arn : null
  description = "GitHub Actions deploy role ARN (push to ECR / deploy)."
}
