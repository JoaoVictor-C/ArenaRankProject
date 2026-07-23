output "primary_endpoint" {
  value       = try(aws_elasticache_replication_group.this.primary_endpoint_address, null)
  description = "Primary endpoint (cluster-mode-disabled)."
}

output "configuration_endpoint" {
  value       = try(aws_elasticache_replication_group.this.configuration_endpoint_address, null)
  description = "Configuration endpoint (cluster-mode-enabled)."
}

output "reader_endpoint" {
  value       = try(aws_elasticache_replication_group.this.reader_endpoint_address, null)
  description = "Reader endpoint."
}

output "port" {
  value = 6379
}

output "security_group_id" {
  value = aws_security_group.redis.id
}
