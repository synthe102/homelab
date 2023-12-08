terraform {
  backend "s3" {
    bucket = "terraform-states-homelab"
    key    = "homelab.tfstate"
    region = "eu-west-1"
  }
  required_version = ">=1.0.0"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.20.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.30.0"
    }
    doppler = {
      source  = "DopplerHQ/doppler"
      version = "~>1.3.0"
    }
  }
}
