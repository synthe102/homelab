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
    talhelper
    just
    sops
    age
    k9s
    cilium-cli
    dig
    argocd
  ];
}
