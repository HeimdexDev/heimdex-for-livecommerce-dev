# ============================================
# Common state reference (VPC, SG)
# ============================================
data "terraform_remote_state" "common" {
  backend = "s3"
  config = {
    bucket = "heimdex-terraform-state"
    key    = "staging/common/terraform.tfstate"
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
# EC2 — import target: i-0aed1a453c71eac46
# ============================================
module "ec2" {
  source = "../../../modules/ec2-instance"

  ami                  = "ami-0dec6548c7c0d0a96"
  instance_type        = "t3.xlarge"
  key_name             = "heimdex-staging-key"
  subnet_id            = data.terraform_remote_state.common.outputs.subnet_id
  security_group_ids   = [data.terraform_remote_state.common.outputs.ec2_security_group_id]
  iam_instance_profile = "heimdex-staging-ec2"

  root_volume_size = 200
  environment      = "staging"
  client_name      = "livenow"

  user_data = templatefile("${path.module}/../../../modules/ec2-instance/templates/user_data.sh.tpl", {
    client_name     = "livenow"
    env_content     = local.env_content
    ssm_param_names = local.ssm_param_names
    ssm_prefix      = "/heimdex/staging/tenants/livenow"
    region          = "ap-northeast-2"
    git_repo        = "git@github.com:jlee-heimdex/heimdex-for-livecommerce-dev.git"
  })
}

# ============================================
# Elastic IP (import target: eipalloc-0c6ecac37479aa1e3)
# ============================================
resource "aws_eip" "this" {
  domain = "vpc"

  tags = {
    Name        = "heimdex-staging-livenow"
    Client      = "livenow"
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
# EC2 IP -> SSM auto-registration (for GitHub Actions deploy)
# ============================================
resource "aws_ssm_parameter" "ec2_host" {
  name  = "/heimdex/staging/tenants/livenow/EC2_HOST"
  type  = "String"
  value = aws_eip.this.public_ip

  tags = {
    ManagedBy = "terraform"
  }
}
