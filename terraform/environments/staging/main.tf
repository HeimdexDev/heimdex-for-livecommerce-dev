# ============================================
# VPC / Subnet / SG — data source (prod common에서 관리)
# ============================================
data "aws_vpc" "main" {
  id = "vpc-03c117173408533fd"
}

data "aws_subnet" "primary" {
  id = "subnet-0ccc47ab2301c638c" # ap-northeast-2d
}

data "aws_security_group" "ec2" {
  id = "sg-0d417a7b3765d4a76"
}

# ============================================
# envs.yaml -> .env conversion
# ============================================
locals {
  env_vars    = yamldecode(file("${path.module}/envs.yaml"))
  env_content = templatefile("${path.module}/../../templates/env.tpl", local.env_vars)

  ssm_param_names = [
    # Secrets
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
    "JWT_SECRET_KEY",
    "DEVICE_SECRET_PEPPER",
    "OPENAI_API_KEY",
    "AGENT_API_KEY",
    "AIRCLOUD_API_KEY",
    "DRIVE_INTERNAL_API_KEY",
    "DRIVE_SA_ENCRYPTION_KEY",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "HF_ACCESS_TOKEN",

    # Service URLs
    "OPENSEARCH_URL",
    "RERANKER_SERVICE_URL",
    "GOOGLE_OAUTH_REDIRECT_URI",
    "SQS_PROCESSING_QUEUE_URL",
    "SQS_CAPTION_QUEUE_URL",
    "SQS_STT_QUEUE_URL",
    "SQS_OCR_QUEUE_URL",
    "SQS_TRANSCODE_QUEUE_URL",
    "SQS_FACE_QUEUE_URL",
    "SQS_VISUAL_EMBED_QUEUE_URL",
    "SQS_EXPORT_QUEUE_URL",
    "SQS_SHORTS_RENDER_QUEUE_URL",
    "SQS_BLUR_QUEUE_URL",
    "SQS_PRODUCT_ENUMERATE_QUEUE_URL",
    "SQS_PRODUCT_TRACK_QUEUE_URL",
    "AIRCLOUD_ENDPOINT_TRANSCODE",
    "AIRCLOUD_ENDPOINT_CAPTION",
    "AIRCLOUD_ENDPOINT_STT",
    "AIRCLOUD_ENDPOINT_OCR",
    "AIRCLOUD_ENDPOINT_FACE",
    "AIRCLOUD_ENDPOINT_VISUAL_EMBED",
    "AIRCLOUD_ENDPOINT_BLUR",
    "AIRCLOUD_ENDPOINT_PRODUCT_ENUMERATE",
    "AIRCLOUD_ENDPOINT_PRODUCT_TRACK",
  ]
}

# ============================================
# Import blocks — existing AWS resources
# ============================================
import {
  to = module.ec2.aws_instance.this
  id = "i-0aed1a453c71eac46"
}

import {
  to = aws_eip.this
  id = "eipalloc-0c6ecac37479aa1e3"
}

# ============================================
# EC2
# ============================================
module "ec2" {
  source = "../../modules/ec2-instance"

  ami                  = "ami-0dec6548c7c0d0a96"
  instance_type        = "t3.xlarge"
  key_name             = "heimdex-staging-key"
  subnet_id            = data.aws_subnet.primary.id
  security_group_ids   = [data.aws_security_group.ec2.id]
  iam_instance_profile = "heimdex-staging-ec2"

  root_volume_size = 200
  environment      = "staging"
  client_name      = "staging"

  user_data = templatefile("${path.module}/../../modules/ec2-instance/templates/user_data.sh.tpl", {
    client_name     = "staging"
    env_content     = local.env_content
    ssm_param_names = local.ssm_param_names
    ssm_prefix      = "/heimdex/staging"
    region          = "ap-northeast-2"
    git_repo        = "git@github.com:jlee-heimdex/heimdex-for-livecommerce-dev.git"
    git_branch      = "main"
  })
}

# ============================================
# Elastic IP (import target: eipalloc-0c6ecac37479aa1e3)
# ============================================
resource "aws_eip" "this" {
  domain = "vpc"

  tags = {
    Name        = "heimdex-staging"
    Environment = "staging"
    ManagedBy   = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip_association" "this" {
  allocation_id = aws_eip.this.id
  instance_id   = module.ec2.instance_id
}

# ============================================
# EC2 IP -> SSM auto-registration
# ============================================
resource "aws_ssm_parameter" "ec2_host" {
  name  = "/heimdex/staging/EC2_HOST"
  type  = "String"
  value = aws_eip.this.public_ip

  tags = {
    ManagedBy = "terraform"
  }
}
