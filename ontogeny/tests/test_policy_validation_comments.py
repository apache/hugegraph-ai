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

from ontogeny.core import validate


def test_validator_ignores_commented_and_quoted_forbid_tokens(golden_pkg):
    golden_pkg.source_texts[("PolicySet", "default")] = """
        // forbid(principal, action == Action::"ignored", Resource::"unrelated");
        /* This comment contains "https://example.test" and
           forbid(principal, action == Action::"ignored", Resource::"unrelated"); */
        forbid /* a comment between tokens */ (principal, action == Action::"read", resource)
            when { resource.name == "https://example.test/a/*literal*/" };
        permit(principal, action == Action::"read", resource)
            when { resource.name == "forbid(example) // /* literal */" };
    """
    report = validate(golden_pkg)
    assert not [issue for issue in report.issues if issue.code in ("POLICY-FORBID", "POLICY-RESOURCE")]


def test_real_unparseable_forbid_is_still_rejected(golden_pkg):
    golden_pkg.source_texts[("PolicySet", "default")] = """
        forbid /* comment between tokens */ (principal, action == Action::"read", resource)
            when { invalid and unsupported
    """
    report = validate(golden_pkg)
    assert any(issue.code == "POLICY-FORBID" for issue in report.issues)


def test_quoted_fake_before_valid_forbid_does_not_block_publication(golden_pkg):
    golden_pkg.source_texts[("PolicySet", "default")] = """
        permit(principal, action == Action::"read", resource)
            when { resource.name == "forbid(fake)" };
        forbid(principal, action == Action::"read", resource);
    """
    report = validate(golden_pkg)
    assert not [issue for issue in report.issues if issue.code == "POLICY-FORBID"]


def test_quoted_fake_cannot_hide_later_resource_scope_error(golden_pkg):
    golden_pkg.source_texts[("PolicySet", "default")] = """
        forbid(principal, action == Action::"read", resource)
            when { resource.name == "permit(fake" };
        permit(principal, action == Action::"read", Resource::"only-one");
    """
    report = validate(golden_pkg)
    assert any(issue.code == "POLICY-RESOURCE" for issue in report.issues)
