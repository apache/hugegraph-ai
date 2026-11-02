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
    schema.property_key("name").as_text().if_not_exist().create()
    schema.property_key("birthDate").as_text().if_not_exist().create()
    schema.vertex_label("Person").properties("name", "birthDate").use_primary_key_id().primary_keys(
        "name"
    ).if_not_exist().create()
    schema.vertex_label("Movie").properties("name").use_primary_key_id().primary_keys("name").if_not_exist().create()
    schema.edge_label("ActedIn").source_label("Person").target_label("Movie").if_not_exist().create()

    """graph"""
    g = client.graph()
    # add Vertex
    p1 = g.add_vertex("Person", {"name": "Al Pacino", "birthDate": "1940-04-25"})
    p2 = g.add_vertex("Person", {"name": "Robert De Niro", "birthDate": "1943-08-17"})
    m1 = g.add_vertex("Movie", {"name": "The Godfather"})
    m2 = g.add_vertex("Movie", {"name": "The Godfather Part II"})
    m3 = g.add_vertex("Movie", {"name": "The Godfather Coda The Death of Michael Corleone"})

    # add Edge
    g.add_edge("ActedIn", p1.id, m1.id, {})
    g.add_edge("ActedIn", p1.id, m2.id, {})
    g.add_edge("ActedIn", p1.id, m3.id, {})
    g.add_edge("ActedIn", p2.id, m2.id, {})

    # update property
    # g.eliminate_vertex("vertex_id", {"property_key": "property_value"})

    # g.remove_vertex_by_id("12:Al Pacino")
    client.close()

    """gremlin"""
    g = client.gremlin()

    """graphs"""
    g = client.graphs()
