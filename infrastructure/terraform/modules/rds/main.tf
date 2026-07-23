# RDS module — PostgreSQL 16, Multi-AZ (proposal §10.1/§10.5: "Multi-AZ with
# automatic failover < 60 seconds"), in private subnets, reachable only from the
# EKS cluster security group. The parameter group preloads pg_stat_statements and
# leaves room for TimescaleDB (`shared_preload_libraries`) — RDS supports the
# timescaledb extension on PG16; enable it with CREATE EXTENSION in a migration.
#
# Trinity findings rely on partitioning + a hypertable (cr_snapshots); those are
# DDL concerns handled by Alembic, not here. This module provisions the engine
# with the right preloads and tuning so those features are available.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db-subnets"
  subnet_ids = var.private_subnet_ids
  tags       = merge(var.tags, { Name = "${var.name}-db-subnets" })
}

resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Postgres ingress from the EKS cluster only."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-db" })
}

resource "aws_security_group_rule" "db_ingress_from_cluster" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.db.id
  source_security_group_id = var.allowed_security_group_id
  description              = "Postgres from EKS pods (via PgBouncer)."
}

resource "aws_security_group_rule" "db_egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.db.id
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Allow all egress."
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name}-pg16"
  family      = "postgres16"
  description = "arenarank PG16 — preloads for timescaledb + pg_stat_statements."

  # TimescaleDB + pg_stat_statements must be in shared_preload_libraries before
  # CREATE EXTENSION will work. Static param → requires a reboot to take effect.
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements,timescaledb"
    apply_method = "pending-reboot"
  }
  # Autovacuum tuning headroom (proposal §4: autovacuum tuning before traffic).
  parameter {
    name  = "autovacuum_vacuum_scale_factor"
    value = "0.05"
  }
  parameter {
    name  = "autovacuum_analyze_scale_factor"
    value = "0.02"
  }
  # Surface slow queries for the postgres_exporter / pg_stat_statements panels.
  parameter {
    name  = "pg_stat_statements.track"
    value = "all"
  }

  tags = var.tags
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name}-pg"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.database_name
  username = var.master_username
  password = var.master_password
  port     = 5432

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.this.name

  backup_retention_period   = var.backup_retention_period # §10.5: 30 days
  backup_window             = "03:00-04:00"
  maintenance_window        = "mon:04:00-mon:05:00"
  copy_tags_to_snapshot     = true
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name}-pg-final"

  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]
  auto_minor_version_upgrade            = true
  apply_immediately                     = var.apply_immediately

  tags = merge(var.tags, { Name = "${var.name}-pg" })
}

# Optional read replica (proposal §10.1: "primary + 1 read replica initially").
resource "aws_db_instance" "replica" {
  count               = var.create_read_replica ? 1 : 0
  identifier          = "${var.name}-pg-ro"
  replicate_source_db = aws_db_instance.this.identifier
  instance_class      = var.replica_instance_class != "" ? var.replica_instance_class : var.instance_class
  storage_encrypted   = true
  multi_az            = false
  skip_final_snapshot = true

  performance_insights_enabled = true
  auto_minor_version_upgrade   = true

  tags = merge(var.tags, { Name = "${var.name}-pg-ro" })
}
