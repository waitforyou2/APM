# AgentCenter 锁文件字段更新

本次更新基于 Workspace 资源支持版本 `41fa0a6`。

## 新格式

对于接口来源的 Skill 和 Knowledge：

- `skill_link_url` 改为 `agentcenter_url`。
- `agentcenter_url` 与 `resolved_url` 都保存完整接口请求地址，包括 `/external/skills/link/v1/get`、`skillId` 和 `version`，两个值必须一致。
- 资源身份及 `deployments.owners`、`active_owner` 使用 `agentcenter:` 前缀。
- 归属标识也包含完整接口路径和 `skillId`，但不包含 `version`，以便升级版本后仍由同一资源负责已有文件。归属标识不用于直接发请求。

以下是锁文件片段示意，不是独立可安装的 Workspace：

```yaml
dependencies:
  - repo_url: geek-security-by-scene-kb
    source: registry
    version: 0.0.1
    agentcenter_url: "https://apigw-cn-south02.huawei.com/api/mcpService/external/skills/link/v1/get?skillId=geek-security-by-scene-kb&version=0.0.1"
    resolved_url: "https://apigw-cn-south02.huawei.com/api/mcpService/external/skills/link/v1/get?skillId=geek-security-by-scene-kb&version=0.0.1"
    # 实际锁文件由安装生成，还包含 ZIP SHA-256、resource 等字段。

deployments:
  - kind: project-relative
    target: cac
    value: .cac/knowledge/geek-security-by-scene-kb/SKILL.md
    runtime: null
    scope: project
    owners:
      - "agentcenter:https://apigw-cn-south02.huawei.com/api/mcpService/external/skills/link/v1/get?skillId=geek-security-by-scene-kb"
    active_owner: "agentcenter:https://apigw-cn-south02.huawei.com/api/mcpService/external/skills/link/v1/get?skillId=geek-security-by-scene-kb"
    # 实际文件还记录 content_hash。
```

## 地址配置

`src/apm_cli/deps/registry/_skill_link_private.py` 现在用 `agentcenter_url` 直接配置完整接口地址，例如 `https://apigw-cn-south02.huawei.com/api/mcpService/external/skills/link/v1/get`。代码不附加固定路径，只从 Workspace 传入 `skillId` 和 `version` 查询参数。已有配置中的 `service_url` 须手动改名并补全接口路径。

Token 接口、认证配置及 `workspace.yml` 的 `id`、`kind`、`version` 写法不需要修改；Git 下载继续使用原有配置。本次不改动私有配置文件，不重命名下载协议的 `provider: skill-link-v1` 配置项，仅统一接口资源的身份标识和锁文件字段。

## 不兼容旧字段

按要求不提供旧字段兼容读取。锁文件中出现 `skill_link_url` 时明确报错，包括该字段为 null 或同时有 `agentcenter_url` 的情况；不会自动迁移、静默忽略或重写旧文件。

建议先在新测试目录放入已有的 `workspace.yml`，执行正常安装生成新锁文件。

如需在原 Workspace 重建，在该 Workspace 目录备份旧锁文件后再安装：

```powershell
if (Test-Path -LiteralPath .\apm.lock.yaml) {
    $lockBackup = "apm.lock.yaml.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff")
    Move-Item -LiteralPath .\apm.lock.yaml -Destination $lockBackup -ErrorAction Stop
}
apm install --no-policy
if ($LASTEXITCODE -ne 0) { throw "Workspace install failed" }
```

重建锁文件会重新建立版本与校验基准，Git 分支可能解析到新的提交；需要保留原 Git 内容时，先将 Workspace 的 `ref` 固定为已验证的提交 SHA。不要用 `--frozen` 创建新锁文件。此更新无需删除 `.cac`；正常安装仍保留原有文件冲突和用户修改保护。

## 验证

本地运行 Registry、Skill Link、自动 Token、混合 Git/API、Workspace、锁文件字段契约与属性测试：445 通过、2 个已有预期失败（xfail）。

本次新增 22 项测试覆盖完整 URL、无版本归属身份、旧字段拒绝、双地址一致性，以及真实 CLI 的安装、刷新、frozen 重装、旧锁文件失败后无写入、备份后重建、卸载。HTTP 采用模拟响应，Git 流程使用本地测试仓库；未连接实际内网服务，未在此环境构建 Windows EXE。

复现命令：

```powershell
uv run pytest -q tests/unit/registry tests/unit/deps/test_lockfile_consumer_contract.py tests/unit/deps/test_lockfile_field_properties.py
```
