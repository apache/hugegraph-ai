# vermeer-python-client

The `vermeer-python-client` is a Python client(SDK) for [Vermeer](https://github.com/apache/hugegraph-computer/tree/master/vermeer#readme) (A high-performance distributed graph computing platform based on memory, supporting more than 15 graph algorithms, custom algorithm extensions, and custom data source access & easy to deploy and use)

## Installation

### Install the released package (🚧 ing)

To install the `vermeer-python-client`, you can use uv/pip:

```bash
# uv is optional, you can use pip directly
# uv pip install vermeer-python-client (Not published yet 🚧ing)
# Note: This will install the latest released version. For the newest code, please install from source.
```

### Install from Source (Latest Code)

To install from the source, clone the repository and install the required dependencies:

```bash
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai/vermeer-python-client

# Use uv sync to install dependencies (standalone module, not in workspace)
uv sync  # Automatically creates .venv and installs dependencies
source .venv/bin/activate  # Activate once - all commands below assume this environment
```

> [!NOTE]
> All usage examples below assume you're in the activated virtual environment

## Usage

This section provides examples of how to use the `vermeer-python-client`.

**Note:** The following examples are placeholders. Please replace them with actual usage scenarios for the `vermeer-python-client`.

### Initialize the Client

```python
from pyvermeer.client.client import PyVermeerClient

# Initialize the client
client = PyVermeerClient(ip="127.0.0.1", port=8688, token="", log_level="DEBUG")
print("Client initialized successfully.")
```

### Example: Creating a Task

```python
from pyvermeer.structure.task_data import TaskCreateRequest

# Example for creating a task
try:
    create_response = client.tasks.create_task(
        create_task=TaskCreateRequest(
            task_type="load",
            graph_name="DEFAULT-example",
            params={
                "load.hg_pd_peers": '["127.0.0.1:8686"]',
                "load.hugegraph_name": "DEFAULT/example/g",
                "load.hugegraph_password": "xxx",
                "load.hugegraph_username": "xxx",
                "load.parallel": "10",
                "load.type": "hugegraph",
            },
        )
    )
    print(f"Create task response: {create_response.to_dict()}")
except Exception as e:
    print(f"Error creating task: {e}")
```

Other info is under 🚧 (Welcome to add more docs for it)

## Contributing

* Welcome to contribute to `vermeer-python-client`. Please see the [Guidelines](https://hugegraph.apache.org/docs/contribution-guidelines/) for more information.
* Code format: Please run `./style/code_format_and_analysis.sh` to format your code before submitting a PR.

Thank you to all the people who already contributed to `vermeer-python-client`!

## Contact Us

* [GitHub Issues](https://github.com/apache/hugegraph-ai/issues): Feedback on usage issues and functional requirements (quick response)
* Feedback Email: [dev@hugegraph.apache.org](mailto:dev@hugegraph.apache.org) (subscriber only)
```
