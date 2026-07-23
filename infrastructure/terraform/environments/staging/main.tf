# Staging root module — 25% prod scale (proposal §10.2). Single NAT, smaller
# nodes/instances, no read replica, deletion protection off for easy teardown.

locals {
  name         = "arenarank-staging"
  cluster_name = "arenarank-staging"
  tags = {
    Project     = "arenarank"
    Environment = "staging"
    ManagedBy   = "terraform"
  }
}

module "network" {
  source             = "../../modules/network"
  name               = local.name
  cluster_name       = local.cluster_name
  vpc_cidr           = "10.1.0.0/16"
  az_count           = 2
  single_nat_gateway = true # cost-saving for staging
  tags               = local.tags
}

module "eks" {
  source              = "../../modules/eks"
  cluster_name        = local.cluster_name
  kubernetes_version  = "1.30"
  private_subnet_ids  = module.network.private_subnet_ids
  public_subnet_ids   = module.network.public_subnet_ids
  node_instance_types = ["m6i.large"]
  node_capacity_type  = "SPOT"
  node_desired_size   = 2
  node_min_size       = 2
  node_max_size       = 6
  tags                = local.tags
}

module "rds" {
  source                    = "../../modules/rds"
  name                      = local.name
  vpc_id                    = module.network.vpc_id
  private_subnet_ids        = module.network.private_subnet_ids
  allowed_security_group_id = module.eks.cluster_security_group_id
  engine_version            = "16.4"
  instance_class            = "db.t4g.medium"
  multi_az                  = false
  backup_retention_period   = 7
  create_read_replica       = false
  deletion_protection       = false
  skip_final_snapshot       = true
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
  node_type                  = "cache.t4g.medium"
  cluster_mode_enabled       = false
  replicas_per_shard         = 0 # single node in staging
  transit_encryption_enabled = false
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
  create_github_oidc = false # reuse the prod-account OIDC provider
  github_repository  = "clesioalopes/arenarank-realoficial"
  tags               = local.tags
}
