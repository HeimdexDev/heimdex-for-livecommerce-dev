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
    key            = "production/tenants/tenant-ebs/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "heimdex-terraform-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "ap-northeast-2"
}
