# SAM3 开放词汇实例分割部署

## 能力定位

平台使用 SAM3 作为统一的开放词汇目标提取能力。用户可以输入一个或多个概念，例如“建筑”“船舶”“车辆”，服务返回每个实例的边界框、掩膜、置信度和编号。后端把推理网格恢复为原影像坐标，生成预览 PNG、合并掩膜 GeoTIFF、实例标签 GeoTIFF、GeoJSON、实例 JSON 与指标 JSON。

旧地物分类运行时及其固定四分类接口已移除。现行工具名为 `segment_instances`，地图框选可以通过 ROI 参数直接限制推理范围。

## CUDA 推理服务

平台后端经 Docker MCP 网关调用 `/infer`。推理服务在配有 NVIDIA GPU 和驱动的主机中运行，可在 `/health` 查看实际使用的设备。网关与推理服务通过同一份任务目录中的输入和结果文件协作。

1. 登录 Meta 的模型页面，按官方流程申请访问。获准后从文件列表下载原版 SAM 3 的 `sam3.pt` 并保存到自己的模型目录，模型文件约 3.45 GB，SHA-256 为 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`。服务启动时会校验文件。权重和上游 SDK 的使用依照各自许可。[Meta 官方权重与访问申请](https://huggingface.co/facebook/sam3) · [获批后下载 sam3.pt](https://huggingface.co/facebook/sam3/resolve/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt?download=true)
2. 在项目根目录使用 Python 3.12 创建独立环境。下面的组合使用 CUDA 12.8 版 PyTorch 和固定提交的 Meta SDK。Windows 可用 `.venv-sam3\Scripts\python.exe` 执行相同的 pip 和 uvicorn 命令。[PyTorch 安装说明](https://pytorch.org/get-started/previous-versions/) · [Meta SDK](https://github.com/facebookresearch/sam3/tree/46957e47805eaa273f4aa7bbbd25a88bca9108ce)

```bash
python3.12 -m venv .venv-sam3
.venv-sam3/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
.venv-sam3/bin/python -m pip install -r ops/sam3_runtime/requirements.txt
```

3. 将 `SAM3_CHECKPOINT_PATH` 指向本地权重文件，`SAM3_ALLOWED_ROOT` 指向已创建的影像目录。该目录必须与后端实际的影像存储共享，服务账号需要读写任务文件。以下路径为示例。

```bash
export SAM3_CHECKPOINT_PATH=/srv/models/sam3/sam3.pt
export SAM3_ALLOWED_ROOT=/srv/agent-rs/imagery
.venv-sam3/bin/python -m uvicorn ops.sam3_service:app --host 127.0.0.1 --port 18082
```

需要由 systemd 托管时，按实际安装路径调整 `ops/agent-rs-sam3.service`，并在 `/etc/agent-rs/sam3.env` 中设置上述变量。服务通过 `GET /health` 报告加载状态、GPU 名称、已核验的权重摘要和 SDK 源码版本。

## Docker MCP 网关

```bash
docker build -t rs-sam3-gateway:local docker/sam3_gateway
```

Linux 同机部署时，后端设置 `SAM3_ENABLED=true`、`SAM3_TRANSPORT=stdio_docker` 和 `SAM3_SERVICE_URL=http://127.0.0.1:18082`。将 `SAM3_UPSTREAM_ROOT` 设置为推理服务视角下的影像目录。使用 Docker Desktop 时，要选择容器能够访问的宿主地址及网络。也可以在同机后端设置 `SAM3_TRANSPORT=local_service` 直接访问回环推理服务。

常驻网关使用独立的私有令牌。Linux 示例从运行环境读取令牌与目录。

```bash
docker run --rm --read-only --tmpfs /tmp --cap-drop ALL --network host \
  -e MCP_TRANSPORT=streamable_http -e MCP_OPERATOR_TOKEN \
  -e SAM3_UPSTREAM_URL=http://127.0.0.1:18082 -e SAM3_UPSTREAM_ROOT \
  rs-sam3-gateway:local
```

后端配置 `SAM3_TRANSPORT=streamable_http`、`SAM3_GATEWAY_URL=http://127.0.0.1:18133/mcp` 和与 `MCP_OPERATOR_TOKEN` 相同的 `SAM3_GATEWAY_TOKEN`。跨主机连接使用受控网络和经过认证的 TLS 入口。网关只传任务引用和分割概念，按上游提交和完成状态返回进度。已有任务的私有目录会在上游状态确定后回收。

`SAM3_MAX_RESOLUTION_M` 默认为 5 米，按实际分析任务设置；后端在调用前校验源影像分辨率。

## 推理与空间恢复

服务按影像原始 RGB 语义读取通道，保留 Alpha/NoData 掩膜：后端导出推理输入 PNG 时以 Alpha 通道标记有效区，服务端把透明像元排除在分割与面积统计之外，全无效切片直接跳过不再占用 GPU。短于分块尺寸的边缘切片先补齐到方形再推理（补齐区与透明区共用同一有效区掩膜，均视为无效），避免非方形输入被模型内部 resize 拉伸变形。跨切片合并完成后，低于最小面积阈值的微小碎片按噪声丢弃，不再计入实例数；阈值由服务侧环境变量 `SAM3_MIN_INSTANCE_AREA` 配置（推理网格像元，默认 32，设 0 关闭）。大影像使用带重叠的分块推理，实例结果在后处理阶段合并。平台侧校验输出网格尺寸，并依据源影像仿射变换生成空间栅格和矢量成果；地理坐标系下不会把平方度误报为平方米。

ROI 与影像必须相交。框选范围不相交、概念无效、服务不可用或推理超时时，工具返回明确错误且不伪造结果。实例数量、轮廓、置信度和面积均属于模型识别结果，使用时应结合原始影像核查。

## 影像语义与位置

波段描述优先，其次使用 GeoTIFF 颜色解释。RGB/Alpha 文件的透明度不是近红外。若前三通道颜色标签不完整、第四通道明确为 Alpha，使用 RGB+Alpha 位置约定，并用 `positional_rgba` 标记该推断。未知多波段文件不会自动猜测传感器。

影像清单包含 WGS84 经纬度四至。`raster_inspect` 同时返回原坐标系四至、WGS84 四至和由仿射变换计算的中心。地图视角中心与影像中心属于不同状态；客户端通过 `metadata.active_imagery_id` 传递当前分析影像，服务端核验资源归属。

## 对话与交互

每次调用模型前移除本轮配额耗尽或前置条件不满足的工具，执行器保留原子配额检查。服务故障会说明原因，不诱导用户不断换轮重试。对话框支持拖动右边缘调整宽度、底边调整高度、右下角同时调整宽高；尺寸保存在浏览器并在窗口缩小时自动限制到可见范围。
