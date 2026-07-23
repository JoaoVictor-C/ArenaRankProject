output "cluster_name" {
  value       = aws_eks_cluster.this.name
  description = "EKS cluster name."
}

output "cluster_endpoint" {
  value       = aws_eks_cluster.this.endpoint
  description = "Kubernetes API server endpoint."
}

output "cluster_ca_data" {
  value       = aws_eks_cluster.this.certificate_authority[0].data
  description = "Base64 cluster CA certificate."
}

output "cluster_security_group_id" {
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  description = "Cluster security group (for datastore ingress rules)."
}

output "oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.oidc.arn
  description = "IRSA OIDC provider ARN."
}

output "oidc_provider_url" {
  value       = replace(aws_iam_openid_connect_provider.oidc.url, "https://", "")
  description = "IRSA OIDC provider URL (no scheme), for trust policies."
}

output "node_role_arn" {
  value       = aws_iam_role.node.arn
  description = "Node group IAM role ARN."
}
