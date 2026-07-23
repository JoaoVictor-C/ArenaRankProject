# ECR module — the private container registry for the single backend image
# (proposal §10.1). Scan-on-push, immutable tags (CI pushes an immutable release
# tag so deploys are reproducible), and a lifecycle policy that prunes untagged
# layers and caps retained images.

resource "aws_ecr_repository" "this" {
  name                 = var.repository_name
  image_tag_mutability = var.image_tag_mutability

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(var.tags, { Name = var.repository_name })
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the last ${var.keep_last_images} tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "main", "staging", "sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.keep_last_images
        }
        action = { type = "expire" }
      }
    ]
  })
}
