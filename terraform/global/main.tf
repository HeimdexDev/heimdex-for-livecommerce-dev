terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-northeast-2"
}

# ============================================
# Terraform State Backend — S3 + DynamoDB
# These resources are the foundation for all other terraform runs.
# Apply once with local state, then migrate to S3 backend.
# ============================================
resource "aws_s3_bucket" "tfstate" {
  bucket = "heimdex-terraform-state" 
  tags = {
    ManagedBy = "terraform"
    Purpose   = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tflock" {
  name         = "heimdex-terraform-lock"
  billing_mode = "PROVISIONED"
  hash_key     = "LockID"

  read_capacity  = 5
  write_capacity = 5

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    ManagedBy = "terraform"
  }
}

# ============================================
# Import blocks — existing AWS resources
# ============================================
import {
  to = aws_s3_bucket.livenow_media_prod
  id = "livenow-media-prod"
}

import {
  to = aws_s3_bucket.drive_staging
  id = "heimdex-drive-staging"
}

import {
  to = aws_s3_bucket.playground
  id = "heimdex-playground"
}

import {
  to = aws_s3_bucket.agent_releases
  id = "heimdex-agent-releases-dc7445ef"
}

import {
  to = aws_s3_bucket.video_archive
  id = "heimdex-video-archive-raw"
}

import {
  to = aws_s3_bucket.face_profiles_test
  id = "heimdex-face-profiles-test-20260325-5lpsbh"
}

# ============================================
# S3 Buckets
# ============================================
resource "aws_s3_bucket" "livenow_media_prod" {
  bucket        = "livenow-media-prod"
  force_destroy = false

  tags = {
    Name        = "livenow-media-prod"
    Environment = "production"
    ManagedBy   = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "drive_staging" {
  bucket        = "heimdex-drive-staging"
  force_destroy = false

  tags = {
    Name        = "heimdex-drive-staging"
    Environment = "staging"
    ManagedBy   = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "playground" {
  bucket        = "heimdex-playground"
  force_destroy = false

  tags = {
    Name      = "heimdex-playground"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "agent_releases" {
  bucket        = "heimdex-agent-releases-dc7445ef"
  force_destroy = false

  tags = {
    Name      = "heimdex-agent-releases"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "video_archive" {
  bucket        = "heimdex-video-archive-raw"
  force_destroy = false

  tags = {
    Name      = "heimdex-video-archive-raw"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "face_profiles_test" {
  bucket        = "heimdex-face-profiles-test-20260325-5lpsbh"
  force_destroy = false

  tags = {
    Name      = "heimdex-face-profiles-test"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}
