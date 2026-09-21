# 平台图表

两张图均依据当前平台源码绘制。SVG 是含可编辑文字的矢量图，PNG 为 1920 像素宽的 README 展示版本。

| 图表 | SVG | PNG |
| --- | --- | --- |
| 平台架构图 | [矢量版](agent-rs-platform-architecture.svg) | [预览版](agent-rs-platform-architecture.png) |
| 遥感分析流程图 | [矢量版](agent-rs-analysis-workflow.svg) | [预览版](agent-rs-analysis-workflow.png) |

## 修改与生成

修改 [`scripts/generate_platform_diagrams.py`](../../scripts/generate_platform_diagrams.py) 中的中文内容、模块或坐标后，在仓库根目录运行：

```bash
python scripts/generate_platform_diagrams.py
```

生成器只使用 Python 标准库，采用逐行拼接 SVG，并检查 XML 语法、文字估算宽度和文字锚点范围。标题和描述使用 SVG 可访问性标签。字体采用本机中文字体，不加载外部字体、图片或脚本。

如已安装 `rsvg-convert`，可导出 PNG：

```bash
rsvg-convert -w 1920 docs/diagrams/agent-rs-platform-architecture.svg -o docs/diagrams/agent-rs-platform-architecture.png
rsvg-convert -w 1920 docs/diagrams/agent-rs-analysis-workflow.svg -o docs/diagrams/agent-rs-analysis-workflow.png
```

也可使用 Sharp / librsvg。以下把可选渲染依赖安装到被 Git 忽略的临时目录，不改变应用依赖清单：

```bash
npm install --prefix .tmp_diagram-render --no-save --package-lock=false sharp
node scripts/render_platform_diagrams.cjs .tmp_diagram-render/node_modules/sharp
```

渲染脚本也支持直接使用已有的 `sharp` 模块路径。系统需有 Microsoft YaHei、PingFang SC 或 Noto Sans CJK SC 等中文字体；不同渲染器与字体版本可能导致像素差异。

## 维护要求

- 图与文字应同时更新；双路径路由、SAM3 HTTP 服务和 MCP / Docker 是不同的执行边界。
- 保留“底图仅 RGB”“报告按需生成”等业务条件；不要把研究方案画成已经上线的能力。
- 生成后打开两张 PNG，检查中文字形、文本边距、箭头方向、线条交叉与图例。
- 检查 README 的相对链接，提交生成脚本、SVG、PNG 与相关文档。

此次图片使用 Sharp / librsvg 导出并完成目视检查。实现解释与源码对应见 [平台架构文档](../platform-architecture.md)。
