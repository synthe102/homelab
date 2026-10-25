# Volcan Minecraft map

BlueMap 5.29 renders the existing Paper 26.3 world and serves it at
<https://mc-map.volcan.cloud>. Chicken/Authentication 0.5.0 links browser sessions
to Minecraft players. Both plugin JARs are pinned in `values.yaml` and installed
by the Minecraft image's `MODRINTH_PROJECTS` mechanism. BlueMap uses version
`5.29-paper`; Authentication uses version ID `xj90zwgY` (`0.5.0-spigot`).
Authentication's Modrinth compatibility labels stop at 26.2, so its exact version
ID is needed on Paper 26.3. Its published SHA-512 matches the GitHub JAR already
validated with Paper 26.3 build 205.

## Login and access

1. Open the map. The French login page displays `/auth <code>`.
2. Join `mc.volcan.cloud` with a whitelisted Minecraft account and run the command.
3. The page checks the session and opens the map once the command succeeds.

Sessions last seven days, with at most three sessions per player. They survive
Pod restarts in `/data/plugins/Authentication/db.sqlite`. IP locking is disabled
so switching between Wi-Fi and mobile data does not invalidate the cookie.
Minecraft online mode and the enforced whitelist are explicitly enabled.

Visit <https://mc-map.volcan.cloud/logout> to sign out of this browser or all your
browsers. Logout uses POST. Removing a player from the whitelist prevents new
in-game authentication but **does not revoke an existing web session**.
For administrator revocation, stop Minecraft, back up the Authentication database,
remove that player's session records, then start the server. This also clears
the plugin's session cache. Permission groups
and automatic whitelist-based session revocation are not implemented.

## Traffic and storage

The existing Cilium HTTPS Gateway forwards the map's HTTPRoute to the map
ClusterIP Service, port 8123. An unprivileged Nginx sidecar checks every map
request against Authentication on `127.0.0.1:8200`, then proxies to BlueMap on
port 8100. That includes assets, tiles, settings, live player positions and SSE.
The login/polling/logout endpoints, logout form and health endpoint contain no
map data and are reachable without a session. Auth errors fail closed.

Nginx overwrites Minecraft identity headers with the authenticated identity and
removes browser cookies and Authorization headers before forwarding to BlueMap.
Map and authentication responses use `private, no-store`; shared CDN caching
must remain disabled for this hostname. Cilium supplies the trusted client
address in `X-Envoy-External-Address`.

The game LoadBalancer keeps the existing `minecraft-volcan` name and only
exposes TCP 25565. Map and metrics have separate ClusterIP Services. The
CiliumNetworkPolicy permits map-proxy traffic only from Cilium's `ingress`
identity and metrics from the monitoring namespace. Other Pod-network traffic,
including direct access to 8100/8200, is denied; Authentication additionally
binds to loopback. The existing scanner deny list and egress rules remain.

The sidecar has no world-data mount. It has a read-only config and root
filesystem and its own 32 MiB temporary volume. BlueMap output and render state
live under `/data/bluemap` on the existing 35 GiB PVC. At first deployment the
map renders only overworld x/z coordinates -2048 through 2048, with one low
priority render thread. The supplied maps directory prevents BlueMap from
automatically creating unbounded maps for other dimensions.

Plugin configuration is synchronized from the generated ConfigMap into the
writable PVC by `COPY_PLUGINS_SRC` on every startup, overriding newer destination
copies. Change the files in `configs/map/`,
not the generated copies on the PVC. Reloader observes the mounted ConfigMaps.

## Validation and rollout

Render the same app-template version as `app.yaml` and validate the manifests:

```sh
helm template minecraft-volcan /path/to/app-template --namespace game-servers \
  --api-versions gateway.networking.k8s.io/v1/HTTPRoute \
  -f clusters/k8s-01/apps/game-servers/minecraft/values.yaml > /tmp/minecraft-rendered.yaml
kubectl kustomize clusters/k8s-01/apps/game-servers/minecraft/configs > /tmp/minecraft-configs.yaml
kubectl -n game-servers apply --dry-run=server \
  -f /tmp/minecraft-rendered.yaml -f /tmp/minecraft-configs.yaml
```

This Application has manual Argo CD sync. Before syncing, back up the existing
PVC and schedule the Minecraft restart. Sync both Helm and config resources,
pruning the old configuration as shown in the preview. Verify:

- The game LoadBalancer retains its address and only exposes 25565; metrics
  scraping continues through the metrics Service.
- BlueMap and Authentication enable without errors; BlueMap produces real tiles.
- Anonymous map, tile and player-data requests redirect to login, and direct
  backend access from another Pod is denied.
- A whitelisted player can authenticate, see the map, log out, and authenticate
  again. Restart the Pod and check that the session persists.
- Watch `/data` free space, JVM memory and server tick times during rendering;
  enlarge `overworld.conf`'s render mask only after measuring the initial render.

Rolling back the values/configs removes the map proxy and Modrinth project entries;
the image tracks the Modrinth-installed JARs for removal. Keep generated map data
and the Authentication database until their deletion is explicitly intended.

## References

- [BlueMap 5.29-paper](https://modrinth.com/plugin/bluemap/version/5.29-paper)
- [Chicken/Auth](https://github.com/Chicken/Auth)
- [Authentication 0.5.0-spigot](https://modrinth.com/plugin/authentication/version/xj90zwgY)
- [Minecraft image Modrinth integration](https://docker-minecraft-server.readthedocs.io/en/latest/mods-and-plugins/modrinth/)
