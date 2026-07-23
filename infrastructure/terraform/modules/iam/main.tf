# IAM module — IRSA roles for the in-cluster ServiceAccounts (api, worker) and a
# GitHub Actions OIDC deploy role for CI/CD (push to ECR + update kubeconfig).
#
# IRSA trust = the EKS OIDC provider + a sub condition pinning the exact
# namespace/serviceaccount, so only those pods can assume the role.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

# --------------------------------------------------------------------------- #
# api IRSA role — read S3 archives, read its secrets.
# --------------------------------------------------------------------------- #
data "aws_iam_policy_document" "api_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:api:api"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${var.name}-api-irsa"
  assume_role_policy = data.aws_iam_policy_document.api_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "api_policy" {
  statement {
    sid       = "S3ReadArchives"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [var.archive_bucket_arn, "${var.archive_bucket_arn}/*"]
  }
  statement {
    sid       = "SecretsRead"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["arn:${local.partition}:secretsmanager:*:${local.account_id}:secret:arenarank/*"]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${var.name}-api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_policy.json
}

# --------------------------------------------------------------------------- #
# worker IRSA role — read/write S3 archives, read secrets.
# --------------------------------------------------------------------------- #
data "aws_iam_policy_document" "worker_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:processing:worker"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.name}-worker-irsa"
  assume_role_policy = data.aws_iam_policy_document.worker_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "worker_policy" {
  statement {
    sid       = "S3ReadWriteArchives"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [var.archive_bucket_arn, "${var.archive_bucket_arn}/*"]
  }
  statement {
    sid       = "SecretsRead"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["arn:${local.partition}:secretsmanager:*:${local.account_id}:secret:arenarank/*"]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "${var.name}-worker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_policy.json
}

# --------------------------------------------------------------------------- #
# GitHub Actions OIDC deploy role — push image to ECR + describe cluster.
# Created only when create_github_oidc = true (the OIDC provider for GitHub must
# exist; this module can create it).
# --------------------------------------------------------------------------- #
resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_github_oidc ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
  tags            = var.tags
}

data "aws_iam_policy_document" "github_trust" {
  count = var.create_github_oidc ? 1 : 0
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  count              = var.create_github_oidc ? 1 : 0
  name               = "${var.name}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_trust[0].json
  tags               = var.tags
}

data "aws_iam_policy_document" "github_policy" {
  count = var.create_github_oidc ? 1 : 0
  statement {
    sid       = "ECRAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid    = "ECRPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = [var.ecr_repository_arn]
  }
  statement {
    sid       = "EKSDescribe"
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:${local.partition}:eks:*:${local.account_id}:cluster/${var.cluster_name}"]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  count  = var.create_github_oidc ? 1 : 0
  name   = "${var.name}-github-actions"
  role   = aws_iam_role.github_actions[0].id
  policy = data.aws_iam_policy_document.github_policy[0].json
}
