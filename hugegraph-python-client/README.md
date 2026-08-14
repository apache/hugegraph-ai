# hugegraph-python-client

The `hugegraph-python-client` is a Python client/SDK for HugeGraph Database.

It is used to define graph structures, perform CRUD operations on graph data, manage schemas, and execute Gremlin queries. Both the `hugegraph-llm` and `hugegraph-ml` modules depend on this foundational library.

## Installation

### Install the released package (Stable)

To install the `hugegraph-python-client`, you can use uv/pip or source code building:

```bash
# uv is optional, you can use pip directly
uv pip install hugegraph-python # Note: may not the latest version, recommend to install from source
# WIP: we will use 'hugegraph-python-client' as the package name soon
```

### Install from Source (Latest Code)

To install from the source, clone the repository and install the required dependencies:

```bash
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai/hugegraph-python-client

# Use uv sync to install dependencies (workspace member)
uv sync  # Automatically creates .venv and installs dependencies
source .venv/bin/activate  # Activate once - all commands below assume this environment
```

> [!NOTE]
> All usage examples below assume you're in the activated virtual environment

## Usage

### Defining Graph Structures

You can use the `hugegraph-python-client` to define graph structures. Below is an example of how to define a graph:

```python
from pyhugegraph.client import PyHugeClient

# Initialize the client
# For HugeGraph API version ≥ v3: (Or enable graphspace function)
# - The 'graphspace' parameter becomes relevant if graphspaces are enabled.(default name is 'DEFAULT')
# - Otherwise, the graphspace parameter is optional and can be ignored.
client = PyHugeClient("127.0.0.1", "8080", user="admin", pwd="admin", graph="hugegraph", graphspace="DEFAULT")

""""
Note:
Could refer to the official REST-API doc of your HugeGraph version for accurate details.
If some API is not as expected, please submit a issue or contact us.
"""
schema = client.schema()
schema.propertyKey("name").asText().ifNotExist().create()
schema.propertyKey("birthDate").asText().ifNotExist().create()
schema.vertexLabel("Person").properties("name", "birthDate").usePrimaryKeyId().primaryKeys("name").ifNotExist().create()
schema.vertexLabel("Movie").properties("name").usePrimaryKeyId().primaryKeys("name").ifNotExist().create()
schema.edgeLabel("ActedIn").sourceLabel("Person").targetLabel("Movie").ifNotExist().create()

print(schema.getVertexLabels())
print(schema.getEdgeLabels())
print(schema.getRelations())

# Init Graph
g = client.graph()
v_al_pacino = g.addVertex("Person", {"name": "Al Pacino", "birthDate": "1940-04-25"})
v_robert = g.addVertex("Person", {"name": "Robert De Niro", "birthDate": "1943-08-17"})
v_godfather = g.addVertex("Movie", {"name": "The Godfather"})
v_godfather2 = g.addVertex("Movie", {"name": "The Godfather Part II"})
v_godfather3 = g.addVertex("Movie", {"name": "The Godfather Coda The Death of Michael Corleone"})

g.addEdge("ActedIn", v_al_pacino.id, v_godfather.id, {})
g.addEdge("ActedIn", v_al_pacino.id, v_godfather2.id, {})
g.addEdge("ActedIn", v_al_pacino.id, v_godfather3.id, {})
g.addEdge("ActedIn", v_robert.id, v_godfather2.id, {})

res = g.getVertexById(v_al_pacino.id).label
print(res)
g.close()
```

### Schema Management

The `hugegraph-python-client` provides comprehensive schema management capabilities.

#### Define Property Keys

```python
# Define a property key
client.schema().propertyKey("name").dataType("STRING").cardinality("SINGLE").create()
```

#### Define Vertex Labels

```python
# Define a vertex label
client.schema().vertexLabel("person").properties("name", "age").primaryKeys("name").create()
```

#### Define Edge Labels

```python
# Define an edge label
client.schema().edgeLabel("knows").sourceLabel("person").targetLabel("person").properties("since").create()
```

#### Define Index Labels

```python
# Define an index label
client.schema().indexLabel("personByName").onV("person").by("name").secondary().create()
```

### CRUD Operations

The client allows you to perform CRUD operations on the graph data. Below are examples of how to create, read, update, and delete vertices and edges:

#### Create Vertices and Edges

```python
# Create vertices
v1 = client.graph().addVertex("person").property("name", "John").property("age", 29).create()
v2 = client.graph().addVertex("person").property("name", "Jane").property("age", 25).create()

# Create an edge
client.graph().addEdge(v1, "knows", v2).property("since", "2020").create()
```

#### Read Vertices and Edges

```python
# Get a vertex by ID
vertex = client.graph().getVertexById(v1.id)
print(vertex)

# Get an edge by ID
edge = client.graph().getEdgeById(edge.id)
print(edge)
```

#### Update Vertices and Edges

```python
# Update a vertex
client.graph().updateVertex(v1.id).property("age", 30).update()

# Update an edge
client.graph().updateEdge(edge.id).property("since", "2021").update()
```

#### Delete Vertices and Edges

```python
# Delete a vertex
client.graph().deleteVertex(v1.id)

# Delete an edge
client.graph().deleteEdge(edge.id)
```

### Execute Gremlin Queries

The client also supports executing Gremlin queries:

```python
# Execute a Gremlin query
g = client.gremlin()
res = g.exec("g.V().limit(5)")
print(res)
```

Other info is under 🚧 (Welcome to add more docs for it, users could refer [java-client-doc]([url](https://hugegraph.apache.org/docs/clients/hugegraph-client/)) for similar usage)

## Contributing

* Welcome to contribute to `hugegraph-python-client`. Please see the [Guidelines](https://hugegraph.apache.org/docs/contribution-guidelines/) for more information.
* Code format: Please run `./style/code_format_and_analysis.sh` to format your code before submitting a PR.

Thank you to all the people who already contributed to `hugegraph-python-client`!

## Contact Us

* [GitHub Issues](https://github.com/apache/hugegraph-ai/issues): Feedback on usage issues and functional requirements (quick response)
* Feedback Email: [dev@hugegraph.apache.org](mailto:dev@hugegraph.apache.org) (subscriber only)
