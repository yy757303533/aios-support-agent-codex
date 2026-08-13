# AIOS 日志与代码地图

本文件用于把售后提供的已脱敏日志路由到组件、进程、仓库和目标版本源码。它只提供定位假设；最终归属必须由日志指纹和对应 CodeContext 中的代码共同确认。

## 日志分层

| 日志或入口 | 主要进程/组件 | 首查内容 | 首查仓库与代码方向 |
|---|---|---|---|
| `/var/log/ai/startup.log` | `zstack_ai_starter`、`run.sh`、`app.sh`、Jupyter 初始化 | 配置生成、模型/代码/数据集准备、挂载、安装和启动阶段 | `aios/devops`、`aios/applications`；配置下发再查 `premium` |
| `/var/log/ai/app.log` | ZSML、vLLM、SGLang、MindIE、Transformers 等推理进程 | 启动命令、模型加载、CUDA/Ray、后端退出、Python Traceback | `aios/inference`、`aios/applications` |
| `/var/log/ai/access.log` | ZSML/MaaS 入口和反向代理 | `/health`、`/readyz`、`/v1/models`、推理请求、404/502 | `aios/inference`，页面调用再查 `zstack-ui-next` |
| `journalctl -u zstack_ai.service` | VM 推理服务 systemd unit | unit 启动、重启、退出码、`ExecStartPre`、stdout/stderr | `aios/devops` 的镜像构建和 unit/starter 资产 |
| `journalctl -u aios-jupyter-lab.service` | JupyterLab | Notebook 服务启动、端口、配置和权限 | `aios/devops` 的 `run.sh` 与 Jupyter 配置逻辑 |
| `management-server.log` | ZStack Management Node | API、资源状态、任务、health check、事件流转 | `zstack`、`premium/plugin-premium/ai` |
| `zstack-kvmagent.log` | KVM Agent | VM、GPU、PCI、驱动、挂载和宿主机侧动作 | `zstack-utility` |
| `/var/log/ai-model-center-agent/` | `model-center-agent.service` | 模型、模板、数据集、服务代码上传下载与管理接口 | `aios/agent` |
| `/var/log/zstack/zstack-dfs/zdfs.log` | `zstack-dfs.service` | ZDFS、JuiceFS/NFS driver、Redis metadata、后端存储与 heartbeat | `aios/dfs` |
| `aios_mount_daemon.log`、`/tmp/aios_mount_daemon.log` | 旧 VM JuiceFS 挂载守护 | mount、subdir、FUSE、重挂载、挂载点卡死 | `aios/devops` 的 `aios_mount_daemon.sh`、`zstack_ai_starter` |
| 容器/Pod 日志 | 容器推理服务、sidecar、推理框架 | 镜像、调度、volume、probe、框架启动 | `aios/inference`、`aios/applications`，编排再查 `premium` |

不要仅凭文件名下根因结论。一个请求可能依次经过 MN、VM/Pod 的 3000 入口和 3001 后端；需要对齐时间、实例标识和请求路径。

## 三个 VM AI 日志

### `startup.log`

主要覆盖：

```text
zstack_ai.service
→ zstack_ai_starter
→ aios-config.sh
→ 模型/代码/数据集准备或挂载
→ run.sh
→ app.sh --install / --start
```

常见定位信号：

- `service.yaml`、`AI_YAML_STRING`、`/etc/aios/env`：配置生成或下发。
- `mount`、`virtiofs`、`juicefs`、`subdir`：数据路径准备。
- `rsync`、`/home/jupyter`、`custom_model_services`：服务代码复制。
- `conda`、`Miniforge3`、`pip`、`app.sh --install`：运行环境安装。
- `app.sh --start`、`start.sh`：进入具体应用启动阶段。

如果日志尚未进入 `app.sh --start`，优先查启动/存储/安装链路；不要先把问题归因于 vLLM 或模型本身。

### `app.log`

主要覆盖 ZSML 和具体推理引擎。常见定位信号：

- `vllm serve`、`EngineCore`、`AsyncLLMEngine`：vLLM。
- `sglang`、`scheduler`、`tokenizer manager`：SGLang。
- `MindIE`、`mindie-service`、Ascend/HCCL：MindIE/昇腾运行时。
- `CUDA out of memory`、`torch.cuda.OutOfMemoryError`：显存不足，仍需核对启动参数和模型规模。
- `NCCL`、`Ray`、`nodeRank`、`tensorParallelSize`：多卡或多机通信。
- `Traceback`、`ModuleNotFoundError`、`ImportError`：Python 环境、应用包或代码路径。

第三方框架日志可能不在 ZStack 源码中。先用框架/类名确认组件，再在目标版本 `aios/applications` 和 `aios/inference` 查启动参数、封装和错误传播；框架内部机制才查对应版本的官方资料。

### `access.log`

主要用于判断入口和后端是否连通：

- `3000`：常见 ZSML/MaaS 对外入口。
- `3001`：常见推理框架内部端口，由 3000 反向代理。
- `8888`：JupyterLab。
- `3000` 可用但 `3001` 不通：入口存活，后端未 ready 或已退出。
- `/readyz` 成功但 `/health` 返回 502：外层进程存活，后端不可用或仍在加载。
- 持续 502：对齐同一分钟的 `app.log`，检查后端启动或退出。
- 404/405：先区分路径/方法不匹配和后端不可用，不要等同于模型加载失败。

## 管控面与宿主机

### `management-server.log`

优先搜索 API 名称、资源 UUID 的脱敏替代符、错误码、消息类和状态迁移。常见代码方向：

- `premium/plugin-premium/ai`：AI 模型、模板、推理服务、实例和 Model Center 管控逻辑。
- `zstack`：通用资源、消息、工作流、数据库对象和基础设施状态。

MN 将实例标记为 `Unknown` 或创建超时时，必须与 VM/Pod 的 `access.log`、`app.log` 和启动日志按时间对齐。MN 的 health-check 结果描述管控面观察，不自动证明后端根因。

### `zstack-kvmagent.log`

常见指纹包括 GPU PCI、libvirt/QEMU、设备透传、驱动、挂载、命令执行和 host-side timeout。首查 `zstack-utility`；若它只是执行 MN 下发参数，再回查 `zstack` 或 `premium` 的调用方。

GPU `Xid`、NVML、NCCL 或驱动错误可能同时出现在 host、VM 和框架日志中。先确认发生层级和时间，不要仅按关键词归属仓库。

## Model Center 与存储

### Model Center Agent

- 服务：`model-center-agent.service`
- 日志：`/var/log/ai-model-center-agent/`
- 代码：`aios/agent`
- 入口：`aios/agent/ai_model_center_agent/agent.py`
- 常见职责：模型、模板、数据集和推理代码的上传、下载、同步与管理接口。

### ZDFS

- 服务：`zstack-dfs.service`
- 日志：`/var/log/zstack/zstack-dfs/zdfs.log`
- 代码：`aios/dfs`
- 主入口：`aios/dfs/src/zdfs/zdfs.go`
- driver：`aios/dfs/src/zdfs/drivers/`
- 常见职责：ZDFS API、JuiceFS/NFS driver、Redis metadata、后端存储和 heartbeat。

Model Center Agent 偏管理和内容入口；ZDFS、Redis metadata、NFS/JuiceFS/virtiofs 属于数据链路。管理接口正常不代表 VM/Pod 一定能读取模型文件。

## 版本分界

- 5.5.28 之前的 VM 推理服务重点检查旧 JuiceFS/ZDFS、Redis metadata、NFS 后端和 `aios_mount_daemon`。
- 5.5.28 及之后重点检查 virtiofs tag、宿主机源路径、VM 内目标路径和服务代码复制。

该分界是检索路由，不能替代目标版本代码证明。必须先生成 CodeContext，再确认目标发布或分支实际采用哪条链路。

## 根据日志反查代码

按以下优先级提取稳定指纹：

1. 完整异常类、错误码、固定英文错误文本。
2. logger 名、Python/Java/Go 包名、类名和函数名。
3. API path、systemd unit、脚本名、配置键。
4. 去除 UUID、IP、客户名和动态数值后的消息模板。

查询步骤：

1. 对原始日志做本地分类，不把完整日志发送给连接器。
2. 通过 `sanitize_query.py` 生成去标识化指纹。
3. 根据本表选择首查仓库。
4. 使用完整 CodeContext 调用 `query_code.py grep`；先搜最稳定、最短的唯一文本。
5. 命中后读取 logger 调用点、异常构造点和直接调用方，不只返回字符串所在文件。
6. 未命中时逐级退化为异常类、API、配置键或组件名；记录“源码未命中”，不要伪造归属。
7. 对第三方日志使用对应版本官方资料，区分“框架产生”与“AIOS 传参/封装导致”。

## 跨层时间线

完整事件至少尝试对齐：

```text
MN 请求与状态迁移
→ Host/容器编排动作
→ startup.log 的准备阶段
→ app.log 的后端加载阶段
→ access.log 的探针和用户请求
```

时间戳时区、节点时间漂移和日志轮转必须显式记录。相邻日志只能证明时间相关，不能单独证明因果。

## 输出要求

内部分析按以下结构记录：

- `log_source`：日志文件或采集入口；未知时写 `unknown`。
- `component`：最可能组件及置信度。
- `deployment_layer`：MN、Host、VM、Container、Model Center 或 Storage。
- `repository`：首查仓库和实际命中仓库。
- `code_context`：版本/分支及冻结 commit 上下文。
- `code_evidence`：错误生成点、logger 调用点和直接调用方。
- `timeline`：与其他层日志的时间关系。
- `uncertainties`：未获得的上下文、未命中项和第三方边界。

对 sales/customer 输出不得包含日志原文、内部路径、仓库、commit、客户标识或内部地址。
