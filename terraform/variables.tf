variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "ac-server"
}

variable "instance_type" {
  description = "EC2 instance type. t3.medium (2 vCPU / 4 GB) is plenty for a private AC server; bump for heavy AI traffic."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GB. Holds the server binaries plus the synced content pack."
  type        = number
  default     = 30
}

variable "allowed_game_cidrs" {
  description = <<-EOT
    CIDR blocks allowed to reach the game ports (9600 TCP/UDP, 8081 TCP).
    Default is open to all so any friend can join by IP. To lock it down to
    specific players, list their IPs as e.g. ["203.0.113.10/32", "198.51.100.5/32"].
  EOT
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "assetto_server_version" {
  description = "AssettoServer release tag to install (e.g. \"v0.0.53\"), or \"latest\" to resolve the newest release at boot."
  type        = string
  default     = "latest"
}

variable "game_tcp_port" {
  description = "AC game TCP port (must match server_cfg.ini TCP_PORT)."
  type        = number
  default     = 9600
}

variable "game_udp_port" {
  description = "AC game UDP port (must match server_cfg.ini UDP_PORT)."
  type        = number
  default     = 9600
}

variable "http_port" {
  description = "AC HTTP port Content Manager reads (must match server_cfg.ini HTTP_PORT)."
  type        = number
  default     = 8081
}
