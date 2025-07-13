{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # https://devenv.sh/packages/
  packages = with pkgs; [
    git
    clusterctl
    talosctl
    just
    k9s
    cilium-cli
    dig
    argocd
    bws
    envsubst
    velero
    kopia
    kubevirt
  ];

  git-hooks.hooks = {
    yamlfmt = {
      enable = true;
      settings.lint-only = false;
    };
  };

  env = {
    COLORTERM = "truecolor";
  };
}
