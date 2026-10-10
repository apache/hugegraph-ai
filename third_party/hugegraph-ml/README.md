# hugegraph-ml

## Summary

`hugegraph-ml` is a tool that integrates HugeGraph with popular graph learning libraries.
It implements most graph learning algorithms, enabling users to perform end-to-end graph learning workflows directly
from HugeGraph using `hugegraph-ml`.
Graph data can be read directly from `HugeGraph` and used for tasks such as node embedding, node classification, and
graph classification.
The implemented algorithm models can be found in the [models](./src/hugegraph_ml/models) folder.

| model       | paper                                              |
|-------------|----------------------------------------------------|
| AGNN        | https://arxiv.org/abs/1803.03735                   |
| APPNP       | https://arxiv.org/abs/1810.05997                   |
| ARMA        | https://arxiv.org/abs/1901.01343                   |
| BGNN        | https://arxiv.org/abs/2101.08543                   |
| BGRL        | https://arxiv.org/abs/2102.06514                   |
| CARE-GNN    | https://arxiv.org/abs/2008.08692                   |
| Cluster-GCN | https://arxiv.org/abs/1905.07953                   |
| C&S         | https://arxiv.org/abs/2010.13993                   |
| DAGNN       | https://arxiv.org/abs/2007.09296                   |
| DeeperGCN   | https://arxiv.org/abs/2006.07739                   |
| DGI         | https://arxiv.org/abs/1809.10341                   |
| DiffPool    | https://arxiv.org/abs/1806.08804                   |
| GATNE       | https://arxiv.org/abs/1905.01669                   |
| GRACE       | https://arxiv.org/abs/2006.04131                   |
| GRAND       | https://arxiv.org/abs/2005.11079                   |
| JKNet       | https://arxiv.org/abs/1806.03536                   |
| P-GNN       | http://proceedings.mlr.press/v97/you19b/you19b.pdf |
| SEAL        | https://arxiv.org/abs/1802.09691                   |

## Environment Requirements

- python 3.9+ (standalone module, not part of workspace)
- hugegraph-server 1.0+ (recommended: 1.5+)
- [uv](https://docs.astral.sh/uv/) 0.7+ (for dependency management)

## Installation

1. Start the HugeGraph database, you can do it via
   Docker/[Binary packages](https://hugegraph.apache.org/docs/download/download/).
   Refer
   to [docker-link](https://hub.docker.com/r/hugegraph/hugegraph) & [deploy-doc](https://hugegraph.apache.org/docs/quickstart/hugegraph-server/#31-use-docker-container-convenient-for-testdev)
   for guidance

2. Clone and setup the project:

   ```bash
   git clone https://github.com/apache/hugegraph-ai.git
   cd hugegraph-ai/hugegraph-ml
   ```

3. Install dependencies using uv:

   ```bash
   # uv sync automatically creates .venv and installs all dependencies
   uv sync
   # Activate virtual environment for easier command usage
   source .venv/bin/activate
   ```

4. Navigate to source directory for examples:

   ```bash
   cd ./src
   ```

> [!NOTE]
> All examples below assume you're in the activated virtual environment

## Examples

### Perform node embedding on the `Cora` dataset using the `DGI` model

Make sure that the Cora dataset is already in your HugeGraph database.
If not, you can run the `import_graph_from_dgl` function to import the `Cora` dataset from `DGL` into
the `HugeGraph` database.

```python
from hugegraph_ml.utils.dgl2hugegraph_utils import import_graph_from_dgl

import_graph_from_dgl("cora")
```

Run [dgi_example.py](./src/hugegraph_ml/examples/dgi_example.py) to view the example.

```bash
python ./hugegraph_ml/examples/dgi_example.py
```

The specific process is as follows:

**1. Graph data convert**

Convert the graph from `HugeGraph` to `DGL` format.

```python
from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.models.dgi import DGI
from hugegraph_ml.models.mlp import MLPClassifier
from hugegraph_ml.tasks.node_classify import NodeClassify
from hugegraph_ml.tasks.node_embed import NodeEmbed

hg2d = HugeGraph2DGL()
graph = hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")
```

**2. Select model instance**

```python
model = DGI(n_in_feats=graph.ndata["feat"].shape[1])
```

**3. Train model and node embedding**

```python
node_embed_task = NodeEmbed(graph=graph, model=model)
embedded_graph = node_embed_task.train_and_embed(add_self_loop=True, n_epochs=300, patience=30)
```

**4. Downstream tasks node classification using MLP**

```python
model = MLPClassifier(
    n_in_feat=embedded_graph.ndata["feat"].shape[1], n_out_feat=embedded_graph.ndata["label"].unique().shape[0]
)
node_clf_task = NodeClassify(graph=embedded_graph, model=model)
node_clf_task.train(lr=1e-3, n_epochs=400, patience=40)
print(node_clf_task.evaluate())
```

**5. Obtain the metrics**

```text
{'accuracy': 0.82, 'loss': 0.5714246034622192}
```

### Perform node classification on the `Cora` dataset using the `GRAND` model.

You can refer to the example in the [grand_example.py](./src/hugegraph_ml/examples/grand_example.py)

```python
from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.models.grand import GRAND
from hugegraph_ml.tasks.node_classify import NodeClassify

hg2d = HugeGraph2DGL()
graph = hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")
model = GRAND(n_in_feats=graph.ndata["feat"].shape[1], n_out_feats=graph.ndata["label"].unique().shape[0])
node_clf_task = NodeClassify(graph, model)
node_clf_task.train(lr=1e-2, weight_decay=5e-4, n_epochs=2000, patience=100)
print(node_clf_task.evaluate())
```
