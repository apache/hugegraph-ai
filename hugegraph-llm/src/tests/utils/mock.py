# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# pylint: disable=unused-argument

import ast

from pyhugegraph.utils.exceptions import ServerError

from hugegraph_llm.models.embeddings.base import BaseEmbedding


class MockEmbedding(BaseEmbedding):
    """Mock embedding class for testing"""

    def __init__(self):
        self.model = "mock_model"

    def get_text_embedding(self, text):
        # Return a simple mock embedding based on the text
        if text == "query1":
            return [1.0, 0.0, 0.0, 0.0]
        if text == "keyword1":
            return [0.0, 1.0, 0.0, 0.0]
        if text == "keyword2":
            return [0.0, 0.0, 1.0, 0.0]
        return [0.5, 0.5, 0.0, 0.0]

    def get_texts_embeddings(self, texts, batch_size: int = 32):
        # Return embeddings for multiple texts
        return [self.get_text_embedding(text) for text in texts]

    async def async_get_text_embedding(self, text):
        # Async version returns the same as the sync version
        return self.get_text_embedding(text)

    async def async_get_texts_embeddings(self, texts, batch_size: int = 32):
        # Async version of get_texts_embeddings
        return [await self.async_get_text_embedding(text) for text in texts]

    def get_llm_type(self):
        return "mock"

    def get_embedding_dim(self):
        # Provide a dummy embedding dimension
        return 4


class VectorIndex:
    """Mock VectorIndex class."""

    def __init__(self, dimension=1536):
        self.dimension = dimension
        self.documents = []
        self.vectors = []

    def add_document(self, document, embedding_model):
        self.documents.append(document)
        self.vectors.append(embedding_model.get_text_embedding(document.content))

    def __len__(self):
        return len(self.documents)

    def search(self, query_vector, top_k=5):
        # Simply return the first top_k documents.
        return self.documents[: min(top_k, len(self.documents))]


class FakeGremlinEndpoint:
    """Stand-in for HugeGraph's /gremlin endpoint that rejects scripts whose g.V(...) ids don't parse.

    Groovy and Python share the same rules for single-quoted literals with \\' and \\\\ escapes,
    so ast.literal_eval acts as the parser. Vertex lookups return matching entries from `vertices`;
    traversals (anything with `.repeat(`) return the `paths` that start at one of the requested ids.
    """

    def __init__(self, vertices, paths=None):
        self.vertices = vertices
        self.paths = paths or []
        self.scripts = []

    @staticmethod
    def _v_args(gremlin):
        """Return the text inside g.V(...), skipping quoted content and escapes; None if it never closes."""
        if not gremlin.startswith("g.V("):
            return None
        quote, depth, i = None, 0, len("g.V(")
        while i < len(gremlin):
            ch = gremlin[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch in "([":
                depth += 1
            elif ch in ")]":
                if depth == 0:
                    return gremlin[len("g.V(") : i]
                depth -= 1
            i += 1
        return None

    def exec(self, gremlin):
        self.scripts.append(gremlin)
        args = self._v_args(gremlin)
        try:
            if args is None:
                raise SyntaxError("unterminated g.V(...) call")
            ids = ast.literal_eval(f"[{args}]")
        except SyntaxError as e:
            raise ServerError(f"Server Exception: startup failed: {e}") from e
        if len(ids) == 1 and isinstance(ids[0], list):  # g.V([...]) is equivalent to g.V(...)
            ids = ids[0]
        if ".repeat(" in gremlin:
            return {"data": [path for path in self.paths if path["objects"][0]["id"] in ids]}
        return {
            "data": [
                {"id": vid, "label": "person", "properties": self.vertices[vid]} for vid in ids if vid in self.vertices
            ]
        }
