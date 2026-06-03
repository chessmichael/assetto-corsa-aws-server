# Use the account's default VPC and its subnets. The server is a single public
# instance; no custom networking is required.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security group: ONLY the game ports are exposed, and only to players.
# There is deliberately no SSH (port 22) rule — the box is managed entirely
# over AWS Systems Manager (SSM), which uses an outbound agent connection.
resource "aws_security_group" "ac" {
  name_prefix = "${var.project_name}-"
  description = "Assetto Corsa game traffic only (no inbound management ports)."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "AC game TCP"
    from_port   = var.game_tcp_port
    to_port     = var.game_tcp_port
    protocol    = "tcp"
    cidr_blocks = var.allowed_game_cidrs
  }

  ingress {
    description = "AC game UDP"
    from_port   = var.game_udp_port
    to_port     = var.game_udp_port
    protocol    = "udp"
    cidr_blocks = var.allowed_game_cidrs
  }

  ingress {
    description = "AC HTTP port (Content Manager / lobby)"
    from_port   = var.http_port
    to_port     = var.http_port
    protocol    = "tcp"
    cidr_blocks = var.allowed_game_cidrs
  }

  # Outbound is open so the box can reach GitHub (server binary), S3 (content),
  # and the SSM endpoints. No inbound management surface is created.
  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
