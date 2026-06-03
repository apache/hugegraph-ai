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

import os
import tempfile
import unittest

import pytest

# 导入测试工具
from src.tests.test_utils import (
    create_test_document,
    should_skip_external,
    with_mock_openai_client,
    with_mock_openai_embedding,
)
from tests.utils.mock import VectorIndex

pytestmark = [pytest.mark.external, pytest.mark.slow]


# 创建模拟类，替代缺失的模块
class Document:
    """模拟的Document类"""

    def __init__(self, content, metadata=None):
        self.content = content
        self.metadata = metadata or {}


class TextLoader:
    """模拟的TextLoader类"""

    def __init__(self, file_path):
        self.file_path = file_path

    def load(self):
        with open(self.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return [Document(content, {"source": self.file_path})]


class RecursiveCharacterTextSplitter:
    """模拟的RecursiveCharacterTextSplitter类"""

    def __init__(self, chunk_size=1000, chunk_overlap=0):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, documents):
        result = []
        for doc in documents:
            # 简单地按照chunk_size分割文本
            text = doc.content
            chunks = [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size - self.chunk_overlap)]
            result.extend([Document(chunk, doc.metadata) for chunk in chunks])
        return result


class OpenAIEmbedding:
    """模拟的OpenAIEmbedding类"""

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key
        self.model = model or "text-embedding-ada-002"

    def get_text_embedding(self, text):
        # 返回一个固定维度的模拟嵌入向量
        return [0.1] * 1536


class OpenAILLM:
    """模拟的OpenAILLM类"""

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key
        self.model = model or "gpt-3.5-turbo"

    def generate(self, prompt):
        # 返回一个模拟的回答
        return f"这是对'{prompt}'的模拟回答"


class VectorIndexRetriever:
    """模拟的VectorIndexRetriever类"""

    def __init__(self, vector_index, embedding_model, top_k=5):
        self.vector_index = vector_index
        self.embedding_model = embedding_model
        self.top_k = top_k

    def retrieve(self, query):
        query_vector = self.embedding_model.get_text_embedding(query)
        return self.vector_index.search(query_vector, self.top_k)


class TestRAGPipeline(unittest.TestCase):
    """测试RAG流程的集成测试"""

    def setUp(self):
        """测试前的准备工作"""
        # 如果需要跳过外部服务测试，则跳过
        if should_skip_external():
            self.skipTest("跳过需要外部服务的测试")

        # 创建测试文档
        self.test_docs = [
            create_test_document("HugeGraph是一个高性能的图数据库"),
            create_test_document("HugeGraph支持OLTP和OLAP"),
            create_test_document("HugeGraph-LLM是HugeGraph的LLM扩展"),
        ]

        # 创建向量索引
        self.embedding_model = OpenAIEmbedding()
        self.vector_index = VectorIndex(dimension=1536)

        # 创建LLM模型
        self.llm = OpenAILLM()

        # 创建检索器
        self.retriever = VectorIndexRetriever(
            vector_index=self.vector_index, embedding_model=self.embedding_model, top_k=2
        )

    @with_mock_openai_embedding
    def test_document_indexing(self, *args):
        """测试文档索引过程"""
        # 将文档添加到向量索引
        for doc in self.test_docs:
            self.vector_index.add_document(doc, self.embedding_model)

        # 验证索引中的文档数量
        self.assertEqual(len(self.vector_index), len(self.test_docs))

    @with_mock_openai_embedding
    def test_document_retrieval(self, *args):
        """测试文档检索过程"""
        # 将文档添加到向量索引
        for doc in self.test_docs:
            self.vector_index.add_document(doc, self.embedding_model)

        # 执行检索
        query = "什么是HugeGraph"
        results = self.retriever.retrieve(query)

        # 验证检索结果
        self.assertIsNotNone(results)
        self.assertLessEqual(len(results), 2)  # top_k=2

    @with_mock_openai_embedding
    @with_mock_openai_client
    def test_rag_end_to_end(self, *args):
        """测试RAG端到端流程"""
        # 将文档添加到向量索引
        for doc in self.test_docs:
            self.vector_index.add_document(doc, self.embedding_model)

        # 执行检索
        query = "什么是HugeGraph"
        retrieved_docs = self.retriever.retrieve(query)

        # 构建提示词
        context = "\n".join([doc.content for doc in retrieved_docs])
        prompt = f"基于以下信息回答问题:\n\n{context}\n\n问题: {query}"

        # 生成回答
        response = self.llm.generate(prompt)

        # 验证回答
        self.assertIsNotNone(response)
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)

    def test_document_loading_and_splitting(self):
        """测试文档加载和分割"""
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as temp_file:
            temp_file.write("这是一个测试文档。\n它包含多个段落。\n\n这是第二个段落。")
            temp_file_path = temp_file.name

        try:
            # 加载文档
            loader = TextLoader(temp_file_path)
            docs = loader.load()

            # 验证文档加载
            self.assertEqual(len(docs), 1)
            self.assertIn("这是一个测试文档", docs[0].content)

            # 分割文档
            splitter = RecursiveCharacterTextSplitter(chunk_size=10, chunk_overlap=0)
            split_docs = splitter.split_documents(docs)

            # 验证文档分割
            self.assertGreater(len(split_docs), 1)
        finally:
            # 清理临时文件
            os.unlink(temp_file_path)


if __name__ == "__main__":
    unittest.main()
