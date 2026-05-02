# ============================================
# VPC — shared with prod, referenced via data source
# ============================================
data "aws_vpc" "main" {
  id = var.vpc_id
}

data "aws_subnet" "primary" {
  id = var.subnet_id
}

# ============================================
# Security Group — shared with prod, referenced via data source
# SG resource is managed in production/common
# ============================================
data "aws_security_group" "ec2" {
  id = var.ec2_security_group_id
}
