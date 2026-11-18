# NVIDIA CUDA 目标检测部署

检测镜像使用 NVIDIA CUDA PyTorch 和 YOLO11s-OBB。按模型来源清单从官方取得 `yolo11s-obb.pt`，放到本地 `docker/rs_detect/` 构建目录。Dockerfile 校验 SHA-256，然后将权重放入供本机使用的镜像。来源及许可证见 [模型清单](../docker/rs_detect/provenance.json)。

安装 NVIDIA 驱动及 Docker GPU 支持后，在项目根目录构建镜像。

```bash
docker build -t rs-detect-mcp:0.2.0 docker/rs_detect
```

后端设置 `RS_DETECT_MCP_IMAGE=rs-detect-mcp:0.2.0`、`RS_DETECT_MCP_ACCELERATOR=nvidia` 和 `RS_DETECT_MCP_GPUS=all`。算子使用 `--gpus all` 访问 GPU，运行期离线读取权重。镜像默认要求 CUDA 可用。

## 推理和输出

分析工作影像按 1024 像素分块、重叠 256 像素；在完整分析网格中恢复旋转框，
同类别按旋转多边形 IoU 0.45 去除重复框。不同类别分别保留，
例如同一场地可以同时有田径场和内部足球场两个候选，不能把候选数当独立设施数。
不同 DOTA 实现的类别编号不同，通过规范化后的名称映射，避免标签错位。
任一维度短于 1024 的边缘切片（含整图小于分块尺寸的情形）先在右侧/下侧补黑色
成 1024 方形再推理，补齐区（切片原尺寸之外）不产生检出框：模型输入恒为原生
尺度的 1024 方形网格，分块边缘不再被 letterbox 自动重采样或注入合成填充；
runtime 指标 `edge_tiles_padded` 记录补齐切片数。该行为随镜像重建生效
（上文 build 命令）。

输出包括唯一命名的透明 PNG、像素旋转框和分数 JSON、WGS84 GeoJSON。
无坐标系时不伪造 GeoJSON。零检测也是成功结果，输出空集合。
所有结果下载继续经过影像所有者鉴权。

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
