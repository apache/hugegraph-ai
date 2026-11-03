# Kubernetes deployment and migration

HugeGraph RAG's standalone `docker/charts/hg-llm` Helm chart is retired in favor
of the canonical `helm/hugegraph` chart in
[`apache/hugegraph`](https://github.com/apache/hugegraph/tree/master/helm/hugegraph).
The canonical integration is [apache/hugegraph#3450](https://github.com/apache/hugegraph/pull/3450)
(development: [hugegraph/hugegraph#365](https://github.com/hugegraph/hugegraph/pull/365)).

**Merge order is mandatory:** #3450 must be merged and its RAG templates
available on ASF `master` **before** this chart retirement is merged. Until
then, ASF `master` cannot install RAG using the instructions below; the fork's
feature branch is a development preview, not a durable deployment target.
The replacement also requires [AI configuration PR #96](https://github.com/hugegraph/hugegraph-ai/pull/96)
and its published `latest`/1.8 RAG image, together with
[the chart simplification](https://github.com/hugegraph/hugegraph/pull/367).
Release order is: application configuration support and image publication,
canonical chart integration, then standalone chart retirement. An older image
cannot implement the new externally mounted configuration contract.

The following installation and migration commands apply only **after**
the canonical chart is available. Do not retire a working legacy release first.

## Fresh installation (no existing `hugegraph` release)

Clone the canonical repository, verify that the integration is present, and
choose **one** topology preset. Use `helm install`, not an upgrade of an
unrelated existing release.

```bash
git clone https://github.com/apache/hugegraph.git
cd hugegraph
git checkout master
test -f helm/hugegraph/values-rag.yaml || { echo "Wait for apache/hugegraph#3450 before installing RAG" >&2; false; }

# Single-node: 1 PD + 1 Store + 1 Server + 1 RAG
helm install hugegraph ./helm/hugegraph \
  -n hugegraph --create-namespace \
  -f helm/hugegraph/values-single.yaml \
  -f helm/hugegraph/values-rag.yaml \
  --set rag.service.type=ClusterIP
```

For a **new** 3+3+3 cluster, change only the preset:

```bash
helm install hugegraph ./helm/hugegraph \
  -n hugegraph --create-namespace \
  -f helm/hugegraph/values-cluster.yaml \
  -f helm/hugegraph/values-rag.yaml \
  --set rag.service.type=ClusterIP
```

RAG is opt-in (`rag.enabled=false` by default). The canonical chart runs **one**
RAG replica for either preset because its mutable prompt and configuration
files are not multi-writer safe. RAG's HTTP Service defaults to an internal
`ClusterIP` in *both* Helm modes; external access is not silently enabled.

For local administrative access from a trusted workstation, use a loopback-only
port-forward:

```bash
kubectl -n hugegraph port-forward \
  service/hugegraph-hugegraph-rag 8001:8001 --address 127.0.0.1
# Browse http://127.0.0.1:8001/ locally.
```

**Security boundary:** The RAG application's own login does **not** protect
every HTTP route. Enabling its UI login is therefore **not sufficient** for
public exposure. Keep `ClusterIP` and ingress disabled by default. If remote
access is necessary, place the Service behind an **authenticated** reverse
proxy/Ingress and restrictive firewall/NetworkPolicy, with TLS and provider
usage limits. In strict mode, explicitly allow only required ingress-controller
and model-provider peers; verify your CNI enforces NetworkPolicy.

A separate HugeGraph database account (rather than the Server administrator)
can be connected using a Kubernetes Secret:

```bash
# Create the account with least-privilege graph permissions first.
kubectl -n hugegraph create secret generic rag-hugegraph-credentials \
  --from-file=password=/secure/path/rag-hugegraph-password
```

```yaml
rag:
  enabled: true
  hugegraph:
    username: rag-service
    passwordSecret:
      name: rag-hugegraph-credentials
      key: password
```

This Secret authenticates **RAG to HugeGraph Server**; it does not add
HTTP authentication to the RAG UI/API. Likewise supply model provider secrets
through `rag.env`/`rag.envFrom`, not plaintext in a values file. See
[canonical RAG documentation](https://github.com/apache/hugegraph/blob/master/helm/hugegraph/docs/rag.md)
for persistent configuration and the approved exposure boundaries.

## Configure RAG outside the container

The canonical chart mounts a writable resource volume at `/var/lib/hugegraph-rag`.
The application uses this root for its editable `.env`, `demo/config_prompt.yaml`,
indexes and generated files. Persistence inherits the top-level setting unless
`rag.persistence.enabled` is explicitly set; use `true` for durable resources
when the existing release disables global persistence. Existing resources are preserved; no files are
copied out automatically from a legacy release.

For operator-owned settings, manage a local env file and prompt YAML, create a
Kubernetes Secret and ConfigMap from them, and mount them through `rag.envFrom`,
`rag.extraVolumes` and `rag.extraVolumeMounts`. Alternatively, mount a complete
`.env` and set `HUGEGRAPH_LLM_ENV_PATH` to its path. Set
`HUGEGRAPH_LLM_PROMPT_CONFIG_PATH` for a separate prompt mount. Read-only
configuration mounts are supported; keep them separate from the writable data
volume. The canonical RAG guide has a complete overlay example. Its resource-root contract
requires both AI #96 and Helm #367, not the earlier #365 image/templates alone.

Configuration precedence is process environment/Secret > mounted `.env` > defaults.
UI/API saves only persist changed fields, and cannot override environment-managed
fields. Startup leaves existing config files unchanged. Update the external
Secret/ConfigMap or volume files and restart RAG to apply changes; entering the
container is unnecessary. UI saves require writable configuration files.

During legacy migration, inspect the old `.env` for automatically saved Secrets
and obsolete provider values. Transfer only settings that should remain
file-managed. Kubernetes-managed credentials should be supplied through Secrets;
when an external graph endpoint requires no password, explicitly clear `GRAPH_PWD`
so a file password from the previous endpoint cannot be reused.

## Add RAG to an existing canonical `hugegraph` release

**Never reapply `values-single.yaml` or `values-cluster.yaml` blindly** to an
existing release: doing so may replace the existing topology, replica counts,
credentials or overrides. Back up and review the existing **user-supplied**
values, then layer only the minimal new RAG configuration. Preserve your
existing `mode`, storage and network settings.

```bash
helm get values hugegraph -n hugegraph -o yaml > hugegraph-existing-values.yaml
# Review this file; preserve any custom PD/Store/Server values.
cat > rag-addition.yaml <<'YAML'
rag:
  enabled: true
  service:
    type: ClusterIP
YAML

helm template hugegraph ./helm/hugegraph -n hugegraph \
  -f helm/hugegraph/values-rag.yaml \
  -f hugegraph-existing-values.yaml -f rag-addition.yaml > /tmp/hugegraph-preview.yaml
# Review the diff against the currently deployed manifests before upgrading.
helm upgrade hugegraph ./helm/hugegraph -n hugegraph \
  -f helm/hugegraph/values-rag.yaml \
  -f hugegraph-existing-values.yaml -f rag-addition.yaml
```

`helm get values` exports explicit overrides, not every previously computed
default. Compare the rendered deployment against the current release and
preserve any relied-upon defaults or overrides before proceeding. Take
application and PVC backups as appropriate.

## Migration mapping from the retired `hg-llm` chart

| Former key | Canonical chart | Migration note |
| --- | --- | --- |
| `image.repository`, `image.tag`, `image.pullPolicy` | `rag.image.*` | Use the updated `latest`/1.8 image containing AI #96; do not blindly reuse an old image |
| `replicaCount` | `rag.replicas` | Only `1` is supported; do not carry a higher value |
| `imagePullSecrets` | top-level `imagePullSecrets` | Shared with other HugeGraph components; review scope |
| `service.type` | `rag.service.type` | Old default `NodePort`; new default **`ClusterIP`** for safety |
| `service.nodePort` | `rag.service.nodePort` | Old default `8039` is outside most Kubernetes default NodePort ranges; set only for an explicitly approved `NodePort` and a valid allocated range |
| `service.port` | **no independent equivalent** | Old `8080` served traffic to `8001`; do **not** set `rag.port=8080` |
| `service.targetPort` | `rag.port` | Keep `8001`, the image's actual HTTP listener; new chart applies it to process, Service and probes together |
| `ingress.*` | `rag.ingress.*` | Disabled by default; add authentication/TLS before enabling |
| `resources` | `rag.resources` | Reassess actual workload needs |
| `podAnnotations`, `podLabels` | `rag.podAnnotations`, `rag.podLabels` | Preserve only nonreserved names |
| `podSecurityContext`, `securityContext` | `rag.podSecurityContext`, `rag.securityContext` | Non-root and strict security defaults cannot be weakened |
| `serviceAccount.*` | `rag.serviceAccount.*` | Token automount must stay disabled |
| `nodeSelector`, `tolerations`, `affinity` | `rag.nodeSelector`, `rag.tolerations`, `rag.affinity` | Copy applicable scheduling rules |
| `livenessProbe`, `readinessProbe` | `rag.probes.liveness`, `rag.probes.readiness` | Map supported paths and tuning, not arbitrary probe objects |
| `volumes`, `volumeMounts` | `rag.extraVolumes`, `rag.extraVolumeMounts` | Review mount collisions with persistent resources |
| `autoscaling.*` | **not supported** | Disable the legacy HPA: current RAG supports one active replica |
| `fullnameOverride`, `nameOverride` | **no RAG equivalent** | Service and Deployment names change; update consumers explicitly |

The old chart uses `fullnameOverride: hg-llm-service`, so clients or ingress
routing to `hg-llm-service` will **not** automatically move to
`<release>-hugegraph-rag` (for release `hugegraph`:
`hugegraph-hugegraph-rag`). Also, the old Service used port `8080` with
target port `8001`, whereas the canonical Service and listener use `8001`.
If preserving distinct Service/target ports is essential, request support in
the canonical chart **before** migrating; never alter `rag.port` to simulate
the old Service port.

## Cut over an existing standalone `hg-llm` release

This is **not** an in-place Helm upgrade: the old RAG release and the canonical
HugeGraph release are separate. Helm will not remove the old release for you.

1. Record `helm get values <old-release> -n <old-namespace> -o yaml`, current
   Service/Ingress names, Secrets, ConfigMaps, volumes and external consumers.
   Back up any `.env`, prompt edits, indexes and other writable RAG data;
   treat `.env` and PVC backups as sensitive.
2. Prepare the canonical HugeGraph chart and convert all applicable old keys
   using the table above. For existing HugeGraph clusters, follow the
   *existing-release* upgrade procedure rather than applying a topology preset.
   Determine how previous ConfigMap mounts and files map to the new RAG PVC;
   the new chart does not automatically migrate old data.
3. Deploy one internal RAG Pod and validate readiness, Server permissions,
   graph/model credentials, prompt resources and persistence through a local
   port-forward. Make sure the new RAG image starts correctly.
4. Switch client DNS/Ingress/proxy routes from `hg-llm-service` (or the actual
   customized old Service) to the new internal Service on port `8001`.
   Validate traffic and rollback routing before removing anything.
5. Only after successful cutover and a verified backup, run
   `helm uninstall <old-release> -n <old-namespace>`. Confirm the old HPA and
   Service are removed and inspect any old PVCs before deleting them.
   Keep a rollback plan until production validation is complete.

## Docker and Compose remain supported

Build the image from the **`hugegraph-ai` repository root** (not the
`hugegraph` Helm repository used above):

```bash
cd ..
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai
docker build -f docker/Dockerfile.llm -t hugegraph/rag .
```

The Docker Compose workflow is also unchanged; see
`docker/docker-compose-llm.yml` in the AI repository.
