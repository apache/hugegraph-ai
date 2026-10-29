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

from types import SimpleNamespace

from ontogeny.policy.engine import PolicyEngine, parse_forbids, parse_policy_set


def engine(text):
    return PolicyEngine(SimpleNamespace(cedar_texts={"default": text}, actions={}))


def test_commented_out_permit_and_forbid_do_not_affect_authorization():
    text = """
    // permit(principal, action == Action::"secret", resource);
    /* forbid(principal, action == Action::"open", resource); */
    permit(principal, action == Action::"open", resource);
    // forbid(principal, action == Action::"open", resource);
    /* permit(principal, action == Action::"secret", resource); */
    """
    assert [r.action for r in parse_policy_set(text)] == ["open"]
    assert parse_forbids(text) == []
    policy = engine(text)
    assert not policy.decide({"id": "alice"}, "secret", {}).allow
    assert policy.decide({"id": "alice"}, "open", {}).allow


def test_comments_between_tokens_and_comment_markers_inside_strings():
    text = """
    permit /* head */ (principal, action == Action::"open", resource)
    when { resource.url == "https://example.test/a/*literal*/" }; // ignored
    forbid(principal, action == Action::"open", resource)
    when { resource.url == "https://example.test/blocked" };
    """
    policy = engine(text)
    assert policy.decide({"id": "alice"}, "open", {"url": "https://example.test/a/*literal*/"}).allow
    assert not policy.decide({"id": "alice"}, "open", {"url": "https://example.test/blocked"}).allow
