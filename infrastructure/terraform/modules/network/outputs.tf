output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet ids (ALB)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet ids (EKS nodes, RDS, ElastiCache)."
  value       = aws_subnet.private[*].id
}

output "azs" {
  description = "Availability zones used."
  value       = local.azs
}
