data "cloudflare_zone" "suslian_engineer" {
  name = "suslian.engineer"
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

resource "doppler_secret" "cert_manager_cloudflare_api_token" {
  project = "homelab"
  config  = "main"
  name    = "CERT_MANAGER_CLOUDFLARE_API_TOKEN"
  value   = cloudflare_api_token.cert_manager.value
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

resource "doppler_secret" "external_dns_cloudflare_api_token" {
  project = "homelab"
  config  = "main"
  name    = "EXTERNAL_DNS_CLOUDFLARE_API_TOKEN"
  value   = cloudflare_api_token.external_dns.value
}
