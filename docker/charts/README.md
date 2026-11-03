---
version: 1.8.0
appVersion: "1.8.0"
---

# Kubernetes deployment

HugeGraph RAG is deployed through the canonical HugeGraph Helm chart in the
[`apache/hugegraph`](https://github.com/apache/hugegraph/tree/master/helm/hugegraph)
repository. The former `docker/charts/hg-llm` chart duplicated the system topology
and has been retired.

The front matter above remains synchronized by `scripts/version.py` so release
metadata stays testable without retaining a second Helm chart.

The integration is introduced by
[`hugegraph/hugegraph#365`](https://github.com/hugegraph/hugegraph/pull/365).
Until that change is merged upstream, use its branch when evaluating the
migration.

## Single-node HugeGraph with RAG

```bash
git clone https://github.com/hugegraph/hugegraph.git
cd hugegraph
git checkout feat/helm-rag-integration

helm upgrade --install hugegraph ./helm/hugegraph \
  -n hugegraph --create-namespace \
  -f helm/hugegraph/values-single.yaml \
  -f helm/hugegraph/values-rag.yaml
```

## HugeGraph cluster with RAG

```bash
helm upgrade --install hugegraph ./helm/hugegraph \
  -n hugegraph --create-namespace \
  -f helm/hugegraph/values-cluster.yaml \
  -f helm/hugegraph/values-rag.yaml
```

Both topologies use the same RAG templates. The topology preset controls the
replica count, while `values-rag.yaml` is the explicit on/off overlay. RAG is
disabled by default.

## Migration mapping

| Former `hg-llm` value | Canonical chart value |
| --- | --- |
| `image.repository`, `image.tag` | `rag.image.repository`, `rag.image.tag` |
| `replicaCount` | `rag.replicas` |
| `service.type` | `rag.service.type` |
| `service.port` | `rag.port` |
| `ingress.*` | `rag.ingress.*` |
| `resources` | `rag.resources` |
| `autoscaling.*` | use a separate HPA targeting the RAG Deployment until native RAG autoscaling is added |

HugeGraph connection settings are now first-class values under
`rag.hugegraph`. When no external URL is supplied, the chart connects RAG to
the same release's Server Service and reuses its administrator Secret.
Provider credentials should be supplied through `rag.envFrom` and Kubernetes
Secrets.

The Docker image workflow is unchanged:

```bash
docker build -f docker/Dockerfile.llm -t hugegraph/rag .
```

The Docker Compose workflow is also unchanged and remains available through
`docker/docker-compose-llm.yml`.
