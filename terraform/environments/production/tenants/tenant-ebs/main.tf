# ============================================
# Common state reference (VPC, SG, RDS)
# ============================================
data "terraform_remote_state" "common" {
  backend = "s3"
  config = {
    bucket = "heimdex-terraform-state"
    key    = "production/common/terraform.tfstate"
    region = "ap-northeast-2"
  }
}

# ============================================
# envs.yaml -> .env conversion
# ============================================
locals {
  env_vars    = yamldecode(file("${path.module}/envs.yaml"))
  env_content = join("\n", [for k, v in local.env_vars : "${k}=${v}"])

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
    "GPG_KEY",
    "HF_ACCESS_TOKEN",
    "LLAMA_CAPTION_API_KEY",
    # Service URLs (kept in SSM to prevent exposure)
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
    "AIRCLOUD_ENDPOINT_TRANSCODE",
    "AIRCLOUD_ENDPOINT_CAPTION",
    "AIRCLOUD_ENDPOINT_STT",
    "AIRCLOUD_ENDPOINT_OCR",
    "AIRCLOUD_ENDPOINT_FACE",
    "AIRCLOUD_ENDPOINT_VISUAL_EMBED",
    "AIRCLOUD_ENDPOINT_BLUR",
    "AIRCLOUD_ENDPOINT_PRODUCT_ENUMERATE",
  ]
}

# ============================================
# EC2 — new instance (no import target)
# ============================================
module "ec2" {
  source = "../../../modules/ec2-instance"

  ami                  = "ami-0ac22ed9e7ba4d3bd"
  instance_type        = "t3.large"
  key_name             = "livenow-prod-key"
  subnet_id            = data.terraform_remote_state.common.outputs.subnet_id
  security_group_ids   = [data.terraform_remote_state.common.outputs.ec2_security_group_id]
  iam_instance_profile = "livenow-prod-ec2-role"

  root_volume_size = 80
  environment      = "production"
  client_name      = "ebs"

  user_data = templatefile("${path.module}/../../../modules/ec2-instance/templates/user_data.sh.tpl", {
    client_name     = "ebs"
    env_content     = local.env_content
    ssm_param_names = local.ssm_param_names
    ssm_prefix      = "/heimdex/prod/tenants/ebs"
    region          = "ap-northeast-2"
    git_repo        = "git@github.com:jlee-heimdex/heimdex-for-livecommerce-dev.git"
  })

  extra_tags = {
    ClientDomain = "ebsdemo.app.heimdexdemo.dev"
  }
}

# ============================================
# Elastic IP
# ============================================
resource "aws_eip" "this" {
  domain = "vpc"

  tags = {
    Name        = "heimdex-prod-ebs"
    Client      = "ebs"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

resource "aws_eip_association" "this" {
  allocation_id = aws_eip.this.id
  instance_id   = module.ec2.instance_id
}

# ============================================
# EC2 IP -> SSM auto-registration (for GitHub Actions deploy)
# ============================================
resource "aws_ssm_parameter" "ec2_host" {
  name  = "/heimdex/prod/tenants/ebs/EC2_HOST"
  type  = "String"
  value = aws_eip.this.public_ip

  tags = {
    ManagedBy = "terraform"
  }
}
