resource "random_password" "tunnel_secret" {
  length = 64
  special = false
}

resource "cloudflare_argo_tunnel" "homelab" {
  name = "homelab"
  account_id = var.cloudflare_account_id
  secret = base64encode(random_password.tunnel_secret.result)
}

data "cloudflare_zone" "suslian_engineer" {
  name = "suslian.engineer"
}

resource "cloudflare_record" "tunnel" {
  zone_id = data.cloudflare_zone.suslian_engineer.id
  type = "CNAME"
  name = "homelab-tunnel"
  value = cloudflare_argo_tunnel.homelab.cname
  proxied = false
  ttl = 1
}

resource "kubernetes_secret" "cloudflared_credentials" {
  metadata {
    name      = "cloudflared-credentials"
    namespace = "cloudflared"
  }

  data = {
    "credentials.json" = jsonencode({
      AccountTag   = var.cloudflare_account_id
      TunnelName   = cloudflare_argo_tunnel.homelab.name
      TunnelID     = cloudflare_argo_tunnel.homelab.id
      TunnelSecret = base64encode(random_password.tunnel_secret.result)
    })
  }
}

data "cloudflare_api_token_permission_groups" "all" {}

resource "cloudflare_api_token" "cert_manager" {
  name = "homelab_cert_manager"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.permissions["Zone Read"],
      data.cloudflare_api_token_permission_groups.all.permissions["DNS Write"]
    ]
    resources = {
      "com.cloudflare.api.account.zone.*" = "*"
    }
  }
}

resource "kubernetes_secret" "cert_manager_token" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = "cert-manager"
  }

  data = {
    "api-token" = cloudflare_api_token.cert_manager.value
  }
}

resource "cloudflare_api_token" "external_dns" {
  name = "homelab_external_dns"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.permissions["Zone Read"],
      data.cloudflare_api_token_permission_groups.all.permissions["DNS Write"]
    ]
    resources = {
      "com.cloudflare.api.account.zone.*" = "*"
    }
  }
}

resource "kubernetes_secret" "external_dns_token" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = "external-dns"
  }

  data = {
    "api-token" = cloudflare_api_token.external_dns.value
  }
}