provider "kubernetes" {
  config_path = "~/.kube/config"
  config_context = "admin@homelab"
}

provider "cloudflare" {}
