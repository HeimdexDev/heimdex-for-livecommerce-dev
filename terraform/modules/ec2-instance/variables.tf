variable "ami" {
  type        = string
  description = "EC2 AMI ID"
}

variable "instance_type" {
  type    = string
  default = "t3.xlarge"
}

variable "key_name" {
  type        = string
  description = "SSH key pair name"
}

variable "subnet_id" {
  type = string
}

variable "security_group_ids" {
  type = list(string)
}

variable "iam_instance_profile" {
  type        = string
  description = "IAM instance profile name"
}

variable "root_volume_size" {
  type    = number
  default = 200
}

variable "root_volume_type" {
  type    = string
  default = "gp3"
}

variable "environment" {
  type = string
}

variable "client_name" {
  type = string
}

variable "user_data" {
  type    = string
  default = null
}

variable "extra_tags" {
  type    = map(string)
  default = {}
}
