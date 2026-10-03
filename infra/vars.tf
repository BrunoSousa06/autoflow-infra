variable "project_name" {
  default = "autoflow"
}

variable "region_default" {
  default = "us-east-1"
}

variable "cidr_vpc" {
  default = "10.0.0.0/16"
}

variable "role_arn" {
  default = "arn:aws:iam::264066152659:role/LabRole"
}
variable "instance_type" {
  default = "t3.medium"
}