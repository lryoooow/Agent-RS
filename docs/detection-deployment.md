# 目标检测与影像语义修复（2026-09-15）

## 部署

旧检测 Docker 镜像未安装，且旧 Paddle CUDA 配方与海光 K100 不兼容。当前使用
YOLO11s-OBB、Ultralytics 8.3.40 和海光 PyTorch 2.1 / torchvision 0.16。
先按 `segmentation-deployment.md` 构建海光 `rs-segment-mcp:0.1.0`，再构建检测镜像。
服务器验证的分割基础镜像 ID 为
`sha256:d0428d34cf674e5056eb0b77ea8e85274a0dbf05c227ec0b50b75a94155b27a0`。

下载 `docker/rs_detect/provenance.json` 指定的官方权重到构建目录，命名
`yolo11s-obb.pt`，校验 SHA256 后执行：

```sh
docker build -t rs-detect-mcp:0.2.0 docker/rs_detect
```

后端配置：

```dotenv
RS_DETECT_MCP_IMAGE=rs-detect-mcp:0.2.0
RS_DETECT_MCP_ACCELERATOR=hygon
RS_DETECT_MCP_GPUS=
RS_DETECT_MCP_MEMORY_LIMIT=8g
RS_DETECT_MCP_CPUS=8
RS_TOOLS_MCP_IMAGE=rs-tools-mcp:0.2.0
```

海光模式映射 `/dev/kfd`、`/dev/mkfd`、`/dev/dri` 和主机 hyhal 库，
不使用 NVIDIA `--gpus`。生产检测镜像额外设置 `RS_DETECT_REQUIRE_GPU=1`，
GPU 不可用时明确失败；运行时 `--network none`，权重预置在镜像中。
未安装镜像、推理超时和服务异常分别返回错误码，不再提示无条件换轮重试。
健康接口报告镜像是否存在；该检查不代替实际模型推理验证。

## 推理和输出

分析工作影像按 1024 像素分块、重叠 256 像素；在完整分析网格中恢复旋转框，
同类别按旋转多边形 IoU 0.45 去除重复框。不同类别分别保留，
例如同一场地可以同时有田径场和内部足球场两个候选，不能把候选数当独立设施数。
不同 DOTA 实现的类别编号不同，通过规范化后的名称映射，避免标签错位。

输出包括唯一命名的透明 PNG、像素旋转框和分数 JSON、WGS84 GeoJSON。
无坐标系时不伪造 GeoJSON。零检测也是成功结果，输出空集合。
所有结果下载继续经过影像所有者鉴权。

真实验证：`fec6252c9325`，4096×4096 分析网格，RGB [1,2,3]，
K100_AI 上 25 个分块约 12.7 秒，阈值 0.5 返回 4 个候选：桥梁 2、
田径场 1、足球场 1。它们是模型预测，尚无标注样本验证精度，不属于建筑提取结果。

## 波段、网格和对话

- 清单、质检、命名波段组合、分类和检测共用源影像的波段语义。
- 原图颜色标签不完整的四波段 Alpha 文件采用 RGB+Alpha 位置约定，明确标注来源；
  不把该约定说成实测光谱定义，也不套用 GF-2 固定波序。
- 真彩色按已解析波段传给 MCP；自定义组合保留显式选项。uint8 保持通道值，保留 Alpha。
- 未确定的 NIR/SWIR 不凭波段数量猜测，Alpha 不作为近红外。
- `source_grid` 和 `analysis_grid` 分别描述原图、推理工作影像。
  本例 6144² / 0.8039m 主动降采样至 4096² / 1.2058m，覆盖范围不变。
- Alpha 0 为透明、255 为不透明；本例全不透明像素 96.39%，全透明 0.0433%。
- 提示词约束不再向用户复述内部上下文处理、不要求用户裁决后台网格差异、
  不从通用失败断言参数无误、不无条件要求换轮重试。

## 开源来源

[Ultralytics YOLO11 文档](https://docs.ultralytics.com/models/yolo11/)、
[固定版本源代码](https://github.com/ultralytics/ultralytics/tree/v8.3.40)。
模型及 Ultralytics 组件采用 AGPL-3.0，完整许可和权重来源见 `docker/rs_detect/`。
平台的开源下载页同时提供本次平台代码与固定版本上游源代码包。

验证覆盖实际 GPU MCP 推理、结果 JSON/GeoJSON、SSE 模型校验、后端回归、前端测试、
公开站点 UI 和真实鉴权下载。UI 使用实际模型结果在临时测试账号中回放，
不冒充用户新对话；未以用户浏览器私有模型 Key 重放整段自然语言对话。
