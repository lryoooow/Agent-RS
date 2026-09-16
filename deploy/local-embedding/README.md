# Hygon 本地 Embedding 部署

已验证环境：Kylin V10、Hygon K100_AI 64 GB、DTK 24.04.1、Python 3.10.21、海光 PyTorch 2.1.0（DAS opt1 / dtk24042）。PyTorch 的 `cuda` 接口在该环境指向 DCU，`torch.version.hip` 为 5.7.24311。不要安装通用 NVIDIA CUDA wheel。

模型：BAAI/bge-m3，MIT，来自 https://modelscope.cn/models/BAAI/bge-m3 ，本地目录 `/home/LRY/models/bge-m3`。向量使用 CLS 池化、float32 L2 归一化，模型在 DCU 上以 float16 推理；原生 1024 维。服务限制单段 2048 tokens，每次请求最多 32 段，内部每批 2 段；超限明确拒绝，文档管线先分块。

运行环境 `/home/LRY/.agent-rs-inference`；服务源码 `/home/LRY/agent-rs-model-service/embedding_server.py`；`agent-rs-embedding.service` 以非 root 用户运行，仅监听 `127.0.0.1:18081`。密钥由服务器生成，位于权限 0600 的 `/etc/agent-rs/embedding.env`，不会进入仓库。运行期启用 HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE，不联网下载模型。

本机运行所需环境：

```text
LD_LIBRARY_PATH=/opt/dtk/lib:/opt/dtk/lib64:/opt/dtk/hip/lib:/opt/dtk/llvm/lib:/usr/local/hyhal/lib
LD_PRELOAD=/usr/lib64/libffi.so.7
```

libffi 预加载仅用于该服务，解决 conda 与系统图形依赖的符号版本冲突；未修改全局动态链接配置。

平台 `EMBEDDING_BASE_URL=http://127.0.0.1:18081/v1`、`EMBEDDING_MODEL=bge-m3`、`EMBEDDING_DIMENSIONS=1024`，API Key 使用本地服务生成的密钥。已有数据库更换模型前必须备份并核对向量维度：本次三张向量表均无非空向量，才将 `agent_rs.messages`、`public.document_chunks`、`public.memories` 的 embedding 列改为 `vector(1024)`。若已有向量，须重新生成，不能直接混用不同模型的数据。上游新建数据库默认仍是 1536 维，重新部署时也需核对。

知识图谱启用 `KNOWLEDGE_GRAPH_ENABLED=true`，LightRAG 的 POSTGRES_* 连接参数由 `/etc/agent-rs/knowledge.env` 注入平台 service；独立数据库为 `agent_rs_knowledge`。应用数据库持久化文档和队列，图数据库保存节点、边与出处。图谱组件使用 LightRAG 1.5.7 的 PGTableGraphStorage；当前关联算法基于结构、平台注册表、工具名称提及和 BGE-M3 语义相似度。开放式实体关系的 LLM 抽取尚未启用。

```bash
systemctl status agent-rs-embedding agent-rs
curl http://127.0.0.1:18081/health
journalctl -u agent-rs-embedding -n 50 --no-pager
```
