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


from decorator import decorator

from pyhugegraph.utils.exceptions import NotAuthorizedError


@decorator
def decorator_params(func, *args, **kwargs):
    parameter_holder = args[0].get_parameter_holder()
    if parameter_holder is None or "name" not in parameter_holder.get_keys():
        raise Exception("Parameters required, please set necessary parameters.")
    return func(*args, **kwargs)


@decorator
def decorator_create(func, *args, **kwargs):
    parameter_holder = args[0].get_parameter_holder()
    if parameter_holder.get_value("not_exist") is False:
        return f'Create failed, "{parameter_holder.get_value("name")}" already exists.'
    return func(*args, **kwargs)


@decorator
def decorator_auth(func, *args, **kwargs):
    response = args[0]
    if response.status_code == 401:
        raise NotAuthorizedError(f"NotAuthorized: {response.content!s}")
    return func(*args, **kwargs)
