# ============================================
# VPC — default VPC, referenced via data source (no import needed)
# ============================================
data "aws_vpc" "main" {
  id = var.vpc_id
}

data "aws_subnet" "primary" {
  id = var.subnet_id
}

# ============================================
# Import blocks — existing AWS resources
# ============================================
import {
  to = aws_security_group.ec2
  id = "sg-0d417a7b3765d4a76"
}

import {
  to = aws_security_group.rds
  id = "sg-01509b6b518637bfd"
}

import {
  to = aws_db_subnet_group.main
  id = "livenow-prod-subnet-group"
}

import {
  to = aws_db_instance.main
  id = "livenow-prod"
}

# ============================================
# Security Group — EC2
# Description must exactly match AWS value (mismatch causes SG recreation)
# ============================================
resource "aws_security_group" "ec2" {
  name        = "livenow-prod-sg"
  description = "Heimdex production - SSH, HTTP, HTTPS"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name      = "livenow-prod-sg"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [name, description]
  }
}

# ============================================
# Security Group — RDS (import target: sg-01509b6b518637bfd)
# ============================================
resource "aws_security_group" "rds" {
  name        = "livenow-prod-rds-sg"
  description = "Heimdex production RDS - Postgres 5432 from EC2"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name      = "livenow-prod-rds-sg"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [name, description]
  }
}

# ============================================
# RDS Subnet Group (import target: livenow-prod-subnet-group)
# ============================================
resource "aws_db_subnet_group" "main" {
  name        = "livenow-prod-subnet-group"
  description = "Heimdex production RDS subnets"
  subnet_ids = [
    "subnet-0baf3aa7294a19b95", # ap-northeast-2a
    "subnet-08c13d6b9f63507e4", # ap-northeast-2b
    "subnet-00d51dbb5e14dfc89", # ap-northeast-2c
    "subnet-0ccc47ab2301c638c", # ap-northeast-2d
  ]

  tags = {
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# ============================================
# RDS — dual protection (import target: livenow-prod)
# All attributes matched to actual AWS values for diff 0
# ============================================
resource "aws_db_instance" "main" {
  identifier     = "livenow-prod"
  engine         = "postgres"
  engine_version = "16.6"
  instance_class = "db.t3.medium"

  db_name  = "heimdex"
  username = "heimdex"
  password = var.db_password

  allocated_storage  = 20
  storage_type       = "gp3"
  iops               = 3000
  storage_throughput = 125
  storage_encrypted  = true
  kms_key_id         = "arn:aws:kms:ap-northeast-2:752198711321:key/76d389b3-784a-4dff-b67f-be71b3ac9574"

  availability_zone    = "ap-northeast-2d"
  multi_az             = false
  publicly_accessible  = false
  db_subnet_group_name = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = "default.postgres16"
  ca_cert_identifier     = "rds-ca-rsa2048-g1"

  backup_retention_period = 7
  backup_window           = "18:00-19:00"
  maintenance_window      = "sun:16:00-sun:17:00"
  auto_minor_version_upgrade   = true
  copy_tags_to_snapshot        = false

  deletion_protection       = true # AWS currently false — will be set to true on apply (intentional)
  skip_final_snapshot       = false
  final_snapshot_identifier = "livenow-prod-final"

  performance_insights_enabled = false
  monitoring_interval          = 0

  tags = {
    Env       = "production"
    Project   = "livenow"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      engine_version,
      password,
      snapshot_identifier,
      final_snapshot_identifier,
    ]
  }
}
