# ElastiCache module — Redis 7 replication group. Defaults to cluster-mode
# disabled (single shard, primary + replicas) which is what arq + the Redlock
# locks + token-bucket Lua want (single keyspace, atomic multi-key Lua). Flip
# cluster_mode_enabled for the proposal's "3 shards" target once the keyspace is
# verified shard-safe. Reachable only from the EKS cluster SG, in private subnets.

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-redis-subnets"
  subnet_ids = var.private_subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "redis" {
  name        = "${var.name}-redis"
  description = "Redis ingress from the EKS cluster only."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-redis" })
}

resource "aws_security_group_rule" "redis_ingress_from_cluster" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.redis.id
  source_security_group_id = var.allowed_security_group_id
  description              = "Redis from EKS pods."
}

resource "aws_security_group_rule" "redis_egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.redis.id
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_elasticache_parameter_group" "this" {
  name   = "${var.name}-redis7"
  family = "redis7"
  # arq queues + caches: evict volatile keys under memory pressure, keep durable
  # queue/lock keys (which we set without TTL) safe.
  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }
  tags = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name}-redis"
  description          = "arenarank Redis (cache, arq queues, locks, token bucket)."
  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  port                 = 6379

  # Cluster-mode-disabled: one node group, N replicas. Cluster-mode-enabled:
  # num_node_groups shards each with replicas_per_node_group replicas.
  num_node_groups         = var.cluster_mode_enabled ? var.num_shards : null
  replicas_per_node_group = var.cluster_mode_enabled ? var.replicas_per_shard : null
  num_cache_clusters      = var.cluster_mode_enabled ? null : (1 + var.replicas_per_shard)

  automatic_failover_enabled = var.replicas_per_shard > 0
  multi_az_enabled           = var.replicas_per_shard > 0

  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.redis.id]
  parameter_group_name = aws_elasticache_parameter_group.this.name

  at_rest_encryption_enabled = true
  transit_encryption_enabled = var.transit_encryption_enabled
  auth_token                 = var.transit_encryption_enabled ? var.auth_token : null

  snapshot_retention_limit = var.snapshot_retention_limit
  snapshot_window          = "05:00-06:00"
  maintenance_window       = "mon:06:00-mon:07:00"
  apply_immediately        = var.apply_immediately

  tags = merge(var.tags, { Name = "${var.name}-redis" })
}
