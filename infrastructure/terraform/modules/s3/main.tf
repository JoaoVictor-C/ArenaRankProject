# S3 module — the archive bucket (season archives, match snapshots, Riot cache
# overflow; proposal §9.3, §10.1, §14.3 cold logs). Private, encrypted, versioned,
# with a lifecycle that tiers cold data to Glacier (proposal §14.3: "1 year cold
# in S3 Glacier").

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name
  tags   = merge(var.tags, { Name = var.bucket_name })
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "archive-to-glacier"
    status = "Enabled"
    filter {
      prefix = "archives/"
    }
    transition {
      days          = 30
      storage_class = "GLACIER"
    }
    expiration {
      days = var.archive_expiration_days
    }
  }

  rule {
    id     = "logs-cold-tier"
    status = "Enabled"
    filter {
      prefix = "logs/"
    }
    transition {
      days          = 30
      storage_class = "GLACIER"
    }
    expiration {
      days = 365 # §14.3: 1 year cold
    }
  }

  rule {
    id     = "abort-incomplete-mpu"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
