variable "vpc_id" {
  type    = string
  default = "vpc-03c117173408533fd"
}

variable "subnet_id" {
  type        = string
  default     = "subnet-0ccc47ab2301c638c" # ap-northeast-2d (same as prod)
  description = "Primary subnet for staging workloads"
}

variable "ec2_security_group_id" {
  type        = string
  default     = "sg-0d417a7b3765d4a76" # livenow-prod-sg (shared with staging)
  description = "EC2 security group — shared with prod"
}
