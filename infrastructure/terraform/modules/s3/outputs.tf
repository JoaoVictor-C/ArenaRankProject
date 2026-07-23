output "bucket_name" {
  value       = aws_s3_bucket.this.id
  description = "Archive bucket name."
}

output "bucket_arn" {
  value       = aws_s3_bucket.this.arn
  description = "Archive bucket ARN (for IAM policies)."
}
