# Third-party notices

## SAM3

Agent-RS 提供 CUDA 推理适配和 Docker MCP 网关。网关镜像只包含网关及其依赖。部署者须通过 Meta 官方渠道取得 SAM 3 的访问授权，安装其 SDK 并按对应许可使用权重。项目的许可证仅覆盖本项目有权授权的内容。[Meta 权重下载与许可](https://huggingface.co/facebook/sam3) · [部署说明](docs/segmentation-deployment.md)

## satvis

The satellite orbit workspace includes a pinned build of [Flowm/satvis](https://github.com/Flowm/satvis), copyright Florian Mauracher and contributors, used under the MIT License. The deployed build includes its `LICENSE.txt` file.

Agent-RS keeps satvis in an isolated iframe and uses its documented URL parameters for satellite selection, task location, time and scene configuration. Satellite orbital elements are refreshed from CelesTrak when the vendor build is produced and are bundled as a static fallback.
