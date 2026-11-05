# Kubernetes deployment

The standalone RAG chart is retired. Deploy RAG with the canonical
[HugeGraph Helm chart](https://github.com/apache/hugegraph/tree/master/helm/hugegraph).
Use a latest/1.8 RAG image that includes the external configuration support in
[apache/hugegraph-ai#396](https://github.com/apache/hugegraph-ai/pull/396).

For a fresh single-node installation, from the `apache/hugegraph` repository:

```bash
helm upgrade --install hugegraph ./helm/hugegraph \
  -n hugegraph --create-namespace \
  -f helm/hugegraph/values-single.yaml \
  -f helm/hugegraph/values-rag.yaml \
  --wait --timeout 15m
kubectl -n hugegraph port-forward svc/hugegraph-hugegraph-rag 8001:8001
```

For a distributed cluster, replace `values-single.yaml` with
`values-cluster.yaml`. RAG runs as one instance in either topology. Open
http://127.0.0.1:8001/ to configure model connections in the web UI. Configure
Chat and Embedding providers before using model-dependent workflows; extraction
and Text2GQL use Chat unless configured separately. Saved settings persist on the
RAG volume. Model credentials are not required in Helm values at installation.

The RAG Service is internal by default. For remote access, put it behind an
authenticated reverse proxy: the application's login does not protect every
HTTP route. See the [canonical RAG guide](https://github.com/apache/hugegraph/blob/master/helm/hugegraph/docs/rag.md)
for deployment requirements, external configuration, storage and security.

Docker and Compose remain supported; see the
[Docker documentation](https://github.com/apache/hugegraph-ai/tree/main/docker).
