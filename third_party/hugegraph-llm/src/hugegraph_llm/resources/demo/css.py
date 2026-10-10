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

CSS = """
footer {
  visibility: hidden
}

.code-container-edit {
    max-height: 520px;
    overflow-y: auto; /* enable scroll */
}

.code-container-show {
    max-height: 250px;
    overflow-y: auto; /* enable scroll */
}

/* FIXME: wrap code is not work as expected now */
.wrap-code {
    white-space: pre-wrap; /* CSS3 */
    white-space: -moz-pre-wrap; /* Mozilla, since 1999 */
    white-space: -pre-wrap; /* Opera 4-6 */
    white-space: -o-pre-wrap; /* Opera 7 */
    word-wrap: break-word; /* Internet Explorer 5.5+ */
}

.output-box {
    border: 1px solid #ccc;
    border-radius: 5px;
    padding: 8px;
    box-sizing: border-box;
    min-height: 50px;
    font-family: Arial, sans-serif;
    line-height: 1.5;
    margin-top: -5px;
    width: 99.5%;
    max-height: 300px;
    overflow-y: auto;
}

.output-box-label {
    font-size: 14px;
    font-weight: bold;
    margin-bottom: -5px;
}

/* Language Indicator Styles */
.header-container {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding: 0 10px;
}

.header-title {
    margin: 0;
    padding: 0;
    font-size: 32px;
    font-weight: 600;
}

.language-indicator {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 24px;
    height: 24px;
    padding: 2px 6px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    cursor: default;
    transition: all 0.2s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
}

.language-indicator.en {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

.language-indicator.cn {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    color: white;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

.language-indicator:hover {
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

/* Custom Tooltip Styles */
.language-indicator-container {
    position: relative;
    display: inline-block;
}

.custom-tooltip {
    position: absolute;
    top: 50%;
    right: 100%;
    transform: translateY(-50%);
    background: rgba(0, 0, 0, 0.8);
    color: white;
    padding: 4px 8px;
    border-radius: 3px;
    font-size: 11px;
    white-space: nowrap;
    z-index: 1000;
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.2s ease;
    margin-right: 8px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.language-indicator-container:hover .custom-tooltip {
    opacity: 1;
    visibility: visible;
}

.custom-tooltip::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 100%;
    transform: translateY(-50%);
    border-top: 3px solid transparent;
    border-bottom: 3px solid transparent;
    border-left: 3px solid rgba(0, 0, 0, 0.8);
}

/* Responsive adjustments */
@media (max-width: 768px) {
    .header-container {
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
    }

    .language-indicator {
        align-self: flex-end;
        margin-top: -10px;
    }
}
"""
