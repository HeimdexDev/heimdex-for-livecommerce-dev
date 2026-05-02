output "vpc_id" {
  value = data.aws_vpc.main.id
}

output "subnet_id" {
  value = data.aws_subnet.primary.id
}

output "ec2_security_group_id" {
  value = data.aws_security_group.ec2.id
}
