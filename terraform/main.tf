########################################
# AMI: latest Ubuntu 24.04 LTS (region-agnostic via SSM public parameter)
########################################
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

########################################
# S3 bucket: staging area for content + rendered configs
########################################
resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "content" {
  bucket        = "${var.project_name}-content-${random_id.suffix.hex}"
  force_destroy = true # allow `terraform destroy` to remove a non-empty bucket
}

resource "aws_s3_bucket_public_access_block" "content" {
  bucket                  = aws_s3_bucket.content.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

########################################
# IAM: instance role for SSM management + read-only access to the content bucket
########################################
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name_prefix        = "${var.project_name}-"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Lets the box be managed by SSM (Run Command, no SSH needed).
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "bucket_read" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.content.arn]
  }
  statement {
    sid       = "ReadObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.content.arn}/*"]
  }
}

resource "aws_iam_role_policy" "bucket_read" {
  name_prefix = "bucket-read-"
  role        = aws_iam_role.instance.id
  policy      = data.aws_iam_policy_document.bucket_read.json
}

resource "aws_iam_instance_profile" "instance" {
  name_prefix = "${var.project_name}-"
  role        = aws_iam_role.instance.name
}

########################################
# EC2 instance + Elastic IP
########################################
locals {
  # user_data.sh is static (no Terraform interpolation). We prepend a shebang
  # and the handful of values the script needs as exported shell variables, so
  # we avoid the templatefile/bash "${}" escaping minefield entirely.
  user_data = join("\n", [
    "#!/bin/bash",
    "export AC_BUCKET=${aws_s3_bucket.content.bucket}",
    "export AC_REGION=${var.region}",
    "export AC_AS_VERSION=${var.assetto_server_version}",
    file("${path.module}/user_data.sh"),
  ])
}

resource "aws_instance" "ac" {
  ami                    = data.aws_ssm_parameter.ubuntu.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.ac.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  user_data                   = local.user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_size = var.root_volume_size
    volume_type = "gp3"
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  tags = {
    Name = "${var.project_name}-instance"
  }
}

resource "aws_eip" "ac" {
  instance = aws_instance.ac.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-eip"
  }
}
