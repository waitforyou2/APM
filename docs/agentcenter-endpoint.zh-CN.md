# 完整配置 AgentCenter 接口地址

管理员只在 `src/apm_cli/deps/registry/_skill_link_private.py` 配置一次完整的下载链接接口地址：

```python
"agentcenter_url": "https://apigw-cn-south02.huawei.com/api/mcpService/external/skills/link/v1/get",
```

代码不再内置或附加 `/external/skills/link/v1/get` 路径。请求时只从 Workspace 读取资源 ID 和版本，添加 `skillId`、`version` 查询参数。配置不要含查询参数、片段或认证信息；路径、大小写及尾斜杠按配置保留。

## 更新已有私有配置

1. 应用源码补丁后，在本机打开 `_skill_link_private.py`。
2. 把 `service_url` 字段名改为 `agentcenter_url`，并把原服务根地址改成完整下载链接接口地址。
3. 保留 `token_url`、`hw_id`、`hw_appkey`、`account` 和 `password` 原值，不要用空模板覆盖整个文件。
4. 重新打包 Windows EXE。补丁不修改私有配置文件，不自动转换旧 `service_url`；旧字段会在请求前报错并提示修改。

获取 Token 的 POST 接口是独立接口，继续由 `token_url` 配置。每次实际调用下载链接接口前，仍先获取新 Token；下载 ZIP 时不传递 API 认证头。

## Workspace 与显式下载源

省略 `registries` 的 Workspace 无需编辑，自动使用管理员配置的完整接口地址。

如果显式写了 `registries.corp-skills.url`，这里也须填完整下载链接接口地址，并与管理员配置一致。使用手动环境变量认证时，本机 `registry.corp-skills.url` 同样绑定完整接口地址，不接受仅绑定上级根路径。原生 APM Registry 的配置语义不变。

下载协议仍是 `provider: skill-link-v1`；本次不新增 MCP 接口适配。

## 锁文件

- `agentcenter_url` 与 `resolved_url` 都为完整请求地址，包含 `skillId` 和 `version`。
- `owners`、`active_owner` 使用 `agentcenter:` 加完整接口路径和 `skillId`；不含版本号，升级后仍属于同一资源。
- 已经采用 `agentcenter_url` 的锁文件，只要实际请求地址不变，就能继续使用，无需重建；`--frozen` 仍按原 URL 和 ZIP 哈希验证。
- 含旧 `skill_link_url` 的锁文件仍不兼容。先备份移走，再执行正常安装生成新锁文件。重新生成会重新建立版本基准，Git 分支可能解析到新的提交。

## 验证结果

457 passed、2 xfailed（已有预期失败），涵盖 Registry、Skill Link、自动 Token、混合 Git/API、Workspace 和锁文件字段契约/属性测试。

新增 13 项接口配置测试，验证自定义接口路径、路径大小写、尾斜杠、安装和冷缓存 frozen 重装、旧私有配置字段拒绝、非法地址拒绝及手动认证的精确接口绑定。测试使用模拟 HTTP 响应及本地 Git 仓库，不访问用户内网或真实认证信息；未构建 Windows EXE。

复现命令：

```powershell
uv run pytest -q tests/unit/registry tests/unit/deps/test_lockfile_consumer_contract.py tests/unit/deps/test_lockfile_field_properties.py
```
