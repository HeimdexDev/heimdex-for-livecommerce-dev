variable "vpc_id" {
  type    = string
  default = "vpc-03c117173408533fd"
}

variable "subnet_id" {
  type        = string
  default     = "subnet-0ccc47ab2301c638c" # ap-northeast-2d
  description = "Primary subnet for production workloads"
}

variable "db_password" {
  type      = string
  sensitive = true
  default   = "placeholder-managed-externally"
}
