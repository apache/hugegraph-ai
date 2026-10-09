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

from pyhugegraph.client import PyHugeClient

if __name__ == "__main__":
    client = PyHugeClient(url="http://127.0.0.1:8080", user="admin", pwd="admin", graph="hugegraph", graphspace=None)

    """schema"""
    schema = client.schema()
    schema.propertyKey("name").asText().ifNotExist().create()
    schema.propertyKey("birthDate").asText().ifNotExist().create()
    schema.vertexLabel("Person").properties("name", "birthDate").usePrimaryKeyId().primaryKeys(
        "name"
    ).ifNotExist().create()
    schema.vertexLabel("Movie").properties("name").usePrimaryKeyId().primaryKeys("name").ifNotExist().create()
    schema.edgeLabel("ActedIn").sourceLabel("Person").targetLabel("Movie").ifNotExist().create()

    """graph"""
    g = client.graph()
    # add Vertex
    p1 = g.addVertex("Person", {"name": "Al Pacino", "birthDate": "1940-04-25"})
    p2 = g.addVertex("Person", {"name": "Robert De Niro", "birthDate": "1943-08-17"})
    m1 = g.addVertex("Movie", {"name": "The Godfather"})
    m2 = g.addVertex("Movie", {"name": "The Godfather Part II"})
    m3 = g.addVertex("Movie", {"name": "The Godfather Coda The Death of Michael Corleone"})

    # add Edge
    g.addEdge("ActedIn", p1.id, m1.id, {})
    g.addEdge("ActedIn", p1.id, m2.id, {})
    g.addEdge("ActedIn", p1.id, m3.id, {})
    g.addEdge("ActedIn", p2.id, m2.id, {})

    # update property
    # g.eliminateVertex("vertex_id", {"property_key": "property_value"})

    # g.removeVertexById("12:Al Pacino")
    g.close()

    """gremlin"""
    g = client.gremlin()

    """graphs"""
    g = client.graphs()
