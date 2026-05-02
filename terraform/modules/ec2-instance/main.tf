resource "aws_instance" "this" {
  ami                    = var.ami
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = var.subnet_id
  vpc_security_group_ids = var.security_group_ids
  iam_instance_profile   = var.iam_instance_profile

  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = var.root_volume_type
    delete_on_termination = false
  }

  user_data = var.user_data

  tags = merge(var.extra_tags, {
    Name        = "heimdex-${var.environment}-${var.client_name}"
    Client      = var.client_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "client-${var.client_name}"
  })

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      ami,
      user_data,
      key_name,
      subnet_id,
      availability_zone,
      ebs_optimized,
      root_block_device,
    ]
  }
}
