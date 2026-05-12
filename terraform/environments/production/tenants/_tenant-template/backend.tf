terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "heimdex-terraform-state"
    key            = "production/tenants/tenant-CHANGEME/terraform.tfstate" # TODO: 고객사명으로 변경
    region         = "ap-northeast-2"
    dynamodb_table = "heimdex-terraform-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "ap-northeast-2"
}
