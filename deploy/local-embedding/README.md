# 本地 BGE-M3 向量服务

使用已安装的 NVIDIA CUDA 版 PyTorch 加载本地 BGE-M3 模型。将 `BGE_MODEL_PATH` 指向已下载的模型目录，设置随机的 `LOCAL_EMBEDDING_API_KEY`。服务使用 float16 推理和归一化 CLS 向量，输出 1024 维。[BGE-M3 模型](https://huggingface.co/BAAI/bge-m3)

在独立的 Python 环境中安装 CUDA 版 PyTorch，再安装本目录的依赖并从本目录启动服务。

```bash
python -m pip install -r requirements.txt
python -m uvicorn embedding_server:app --host 127.0.0.1 --port 18081
```

平台侧设置 `EMBEDDING_BASE_URL=http://127.0.0.1:18081/v1`、`EMBEDDING_MODEL=bge-m3`、`EMBEDDING_DIMENSIONS=1024` 与对应密钥。切换模型前应核对数据库向量维度，对已有向量按新模型重新索引。
