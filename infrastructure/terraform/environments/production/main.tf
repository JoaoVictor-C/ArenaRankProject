# Production root module — composes network → eks → {rds, elasticache, s3, ecr}
# → iam (IRSA + CI deploy). Datastores attach to the EKS cluster security group
# so only in-cluster pods reach them. Remote state lives in S3 + DynamoDB lock
# (see backend.tf).

locals {
  name         = "arenarank-prod"
  cluster_name = "arenarank-prod"
  tags = {
    Project     = "arenarank"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

module "network" {
  source             = "../../modules/network"
  name               = local.name
  cluster_name       = local.cluster_name
  vpc_cidr           = "10.0.0.0/16"
  az_count           = 3
  single_nat_gateway = false # one NAT per AZ for HA in prod
  tags               = local.tags
}

module "eks" {
  source              = "../../modules/eks"
  cluster_name        = local.cluster_name
  kubernetes_version  = "1.30"
  private_subnet_ids  = module.network.private_subnet_ids
  public_subnet_ids   = module.network.public_subnet_ids
  node_instance_types = ["m6i.large"]
  node_desired_size   = 4
  node_min_size       = 3
  node_max_size       = 20
  tags                = local.tags
}

module "rds" {
  source                    = "../../modules/rds"
  name                      = local.name
  vpc_id                    = module.network.vpc_id
  private_subnet_ids        = module.network.private_subnet_ids
  allowed_security_group_id = module.eks.cluster_security_group_id
  engine_version            = "16.4"
  instance_class            = "db.r6g.large"
  multi_az                  = true
  backup_retention_period   = 30
  create_read_replica       = true
  deletion_protection       = true
  master_password           = var.rds_master_password
  tags                      = local.tags
}

module "elasticache" {
  source                     = "../../modules/elasticache"
  name                       = local.name
  vpc_id                     = module.network.vpc_id
  private_subnet_ids         = module.network.private_subnet_ids
  allowed_security_group_id  = module.eks.cluster_security_group_id
  engine_version             = "7.1"
  node_type                  = "cache.r6g.large"
  cluster_mode_enabled       = false
  replicas_per_shard         = 1
  transit_encryption_enabled = true
  auth_token                 = var.redis_auth_token
  tags                       = local.tags
}

module "s3" {
  source      = "../../modules/s3"
  bucket_name = "${local.name}-archives-${var.account_id}"
  tags        = local.tags
}

module "ecr" {
  source          = "../../modules/ecr"
  repository_name = "arenarank-backend"
  tags            = local.tags
}

module "iam" {
  source             = "../../modules/iam"
  name               = local.name
  oidc_provider_arn  = module.eks.oidc_provider_arn
  oidc_provider_url  = module.eks.oidc_provider_url
  archive_bucket_arn = module.s3.bucket_arn
  ecr_repository_arn = module.ecr.repository_arn
  cluster_name       = module.eks.cluster_name
  create_github_oidc = true
  github_repository  = "clesioalopes/arenarank-realoficial"
  tags               = local.tags
}
