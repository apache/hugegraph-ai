#! /bin/bash
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

BLACK=false
PYLINT=false
ROOT_DIR=$(pwd)
echo ${ROOT_DIR}
# Parse command line arguments
while getopts ":bp" opt; do
  case ${opt} in
    b )
      BLACK=true
      ;;
    p )
      PYLINT=true
      ;;
    \? )
      echo "Usage: cmd [-b] [-p]"
      ;;
  esac
done

# If no arguments were provided, run both BLACK and PYLINT
if [ "$BLACK" = false ] && [ "$PYLINT" = false ]; then
  BLACK=true
  PYLINT=true
fi

# Run BLACK if -b is specified
if [ "$BLACK" = true ] ; then
  echo "[black] Start to check code style and auto format"
  # https://github.com/psf/BLACK/issues/1802
  black --line-length=120 ${ROOT_DIR}
fi

# Run PYLINT if -p is specified
if [ "$PYLINT" = true ] ; then
  echo "[pylint] Start code analysis and check,
  we need to manually fix all the warnings mentioned below before commit! "
  export PYTHONPATH=${ROOT_DIR}/hugegraph-llm/src:${ROOT_DIR}/hugegraph-python-client/src:${ROOT_DIR}/hugegraph-ml/src
  pylint --rcfile=${ROOT_DIR}/style/pylint.conf ${ROOT_DIR}/hugegraph-llm ${ROOT_DIR}/hugegraph-ml ${ROOT_DIR}/hugegraph-python-client
fi
