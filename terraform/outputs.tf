output "public_ip" {
  description = "Stable Elastic IP of the server. Use this in Content Manager."
  value       = aws_eip.ac.public_ip
}

output "instance_id" {
  description = "EC2 instance id (used by the ac CLI for SSM commands and start/stop)."
  value       = aws_instance.ac.id
}

output "content_bucket" {
  description = "S3 bucket the ac CLI syncs content and configs to."
  value       = aws_s3_bucket.content.bucket
}

output "region" {
  description = "AWS region everything lives in."
  value       = var.region
}

output "http_port" {
  description = "HTTP port Content Manager connects to."
  value       = var.http_port
}

output "cm_connect" {
  description = "Address to add in Content Manager (Online > add server by IP)."
  value       = "${aws_eip.ac.public_ip}:${var.http_port}"
}

output "info_url" {
  description = "Quick health check once the server is running."
  value       = "http://${aws_eip.ac.public_ip}:${var.http_port}/INFO"
}
