output "endpoint" {
  value       = aws_db_instance.this.endpoint
  description = "Primary DB endpoint (host:port)."
}

output "address" {
  value       = aws_db_instance.this.address
  description = "Primary DB hostname."
}

output "port" {
  value       = aws_db_instance.this.port
  description = "DB port."
}

output "database_name" {
  value       = aws_db_instance.this.db_name
  description = "Initial database name."
}

output "read_replica_endpoint" {
  value       = var.create_read_replica ? aws_db_instance.replica[0].endpoint : null
  description = "Read replica endpoint, if created."
}

output "security_group_id" {
  value       = aws_security_group.db.id
  description = "DB security group id."
}
