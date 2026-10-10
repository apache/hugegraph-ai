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


import json
import re

REGEX = (
    r"Nodes:\s+(.*?)\s?\s?" r"Relationships:\s?\s?" r"NodesSchemas:\s+(.*?)\s?\s?" r"RelationshipsSchemas:\s?\s?(.*)"
)
INTERNAL_REGEX = r"\[(.*?)\]"
JSON_REGEX = r"\{.*\}"
JSON_REGEX_RELATIONSHIPS = r"\{.*?\}"


def nodes_text_to_list_of_dict(nodes):
    result = []
    for node in nodes:
        node_list = node.split(",")
        if len(node_list) < 2:
            continue

        name = node_list[0].strip().replace('"', "")
        label = node_list[1].strip().replace('"', "")
        properties = re.search(JSON_REGEX, node)
        if properties is None:
            properties = "{}"
        else:
            properties = properties.group(0)
        properties = properties.replace("True", "true")
        properties = properties.replace("\\", "")
        try:
            properties = json.loads(properties)
        except json.decoder.JSONDecodeError:
            properties = {}
        result.append({"name": name, "label": label, "properties": properties})
    return result


def relationships_text_to_list_of_dict(relationships):
    result = []
    for relationship in relationships:
        relationship_list = relationship.split(",")
        if len(relationship_list) < 3:
            continue
        start = {}
        end = {}
        properties = {}
        relationship_type = relationship_list[1].strip().replace('"', "")
        matches = re.findall(JSON_REGEX_RELATIONSHIPS, relationship)
        i = 1
        for match in matches:
            if i == 1:
                start = json.loads(match)
                i = 2
                continue
            if i == 2:
                end = json.loads(match)
                i = 3
                continue
            if i == 3:
                properties = json.loads(match)
        result.append(
            {
                "start": start,
                "end": end,
                "type": relationship_type,
                "properties": properties,
            }
        )
    return result


def nodes_schemas_text_to_list_of_dict(nodes_schemas):
    result = []
    for nodes_schema in nodes_schemas:
        nodes_schema_list = nodes_schema.split(",")
        if len(nodes_schema) < 1:
            continue

        label = nodes_schema_list[0].strip().replace('"', "")
        primary_key = nodes_schema_list[1].strip().replace('"', "")
        properties = re.search(JSON_REGEX, nodes_schema)
        if properties is None:
            properties = "{}"
        else:
            properties = properties.group(0)
        properties = properties.replace("True", "true")
        try:
            properties = json.loads(properties)
        except json.decoder.JSONDecodeError:
            properties = {}
        result.append({"label": label, "primary_key": primary_key, "properties": properties})
    return result


def relationships_schemas_text_to_list_of_dict(relationships_schemas):
    result = []
    for relationships_schema in relationships_schemas:
        relationships_schema_list = relationships_schema.split(",")
        if len(relationships_schema_list) < 3:
            continue
        start = relationships_schema_list[0].strip().replace('"', "")
        end = relationships_schema_list[2].strip().replace('"', "")
        relationships_schema_type = relationships_schema_list[1].strip().replace('"', "")

        properties = re.search(JSON_REGEX, relationships_schema)
        if properties is None:
            properties = "{}"
        else:
            properties = properties.group(0)
        properties = properties.replace("True", "true")
        try:
            properties = json.loads(properties)
        except json.decoder.JSONDecodeError:
            properties = {}
        result.append(
            {
                "start": start,
                "end": end,
                "type": relationships_schema_type,
                "properties": properties,
            }
        )
    return result
