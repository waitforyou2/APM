# AgentCenter 锁文件 host 修正

AgentCenter 依赖在解析时，自动从完整 `agentcenter_url` 提取主机名，写入依赖引用和生成的锁文件。例如：

```yaml
host: apigw-cn-south02.huawei.com
```

这里记录获取下载链接的接口域名，不包含协议、端口、路径或查询参数，也不使用获取 Token 的域名或临时 ZIP 存储域名。实际请求仍使用完整接口 URL，包括自定义端口。

无需新增 `host` 配置，也无需修改 Workspace、接口地址或认证配置。Git 资源继续记录 Git 仓库的主机名；本次未修改通用 Registry 解析器或官方默认 host。

## 更新旧锁文件

应用补丁并重新打包 EXE 后，在 Workspace 目录执行：

```powershell
& $apm install --refresh --no-policy
if ($LASTEXITCODE -ne 0) { throw "Workspace install failed" }
```

此步骤会实际刷新依赖；既有 AgentCenter 锁文件的 ZIP 哈希约束仍然有效，版本、接口、资源归属标识和部署路径不会因 host 修正而改变。Git 浮动分支在刷新时可能解析到新提交。

无须删除锁文件。已有锁文件若仍写着 `github.com`，不要依赖仅使用缓存的安装来完成字段更新；先运行上述刷新命令，再恢复日常安装或 `--frozen` 使用。

## 验证

201 passed、17 xfailed。命令：

```powershell
uv run pytest -q tests/unit/registry/test_skill_link.py tests/unit/registry/test_skill_link_auto_token.py tests/unit/registry/test_skill_link_builtin.py tests/unit/registry/test_workspace_resources.py tests/unit/registry/test_agentcenter_lock.py tests/unit/registry/test_agentcenter_endpoint.py tests/unit/test_drift_registry.py tests/unit/test_reference_registry_shorthand.py
```

覆盖新安装、旧 host 刷新、skills/knowledge、显式/内置源、不同接口域名及端口、冷热缓存 frozen 重装、Git/API 混合安装、移除资源以及已有认证和锁文件校验。使用模拟 HTTP 与本地 Git 仓库；未访问用户内网或构建 Windows EXE。

生产代码仅修改 `src/apm_cli/deps/registry/skill_link_config.py`，新增一次 host 赋值及说明注释，以减少与上游 APM 的合并冲突。
