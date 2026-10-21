# Workspace resources 验证结果

日期：2026-10-21

基线：waitforyou2/APM main，3fe8f2b675276c803693c6df93aee8e5d5218fb8。

## 自动化验证

- 选定回归：987 passed、2 xfailed、50 warnings，22.01 秒。
- 本功能新增测试：24 项，包含完整命令行安装/卸载流程。
- 2 个 xfailed 是 Registry 测试中的既有预期失败。
- Git diff whitespace 检查通过；48 个修改/新增 Python 文件格式检查通过。
- Ruff 没有新增问题。当前环境的 Ruff 对 6 个既有函数报告 PLR0917；
  已与基线逐项比较，错误内容一致。本补丁未放宽仓库的 lint 配置。

## 覆盖内容

- 四种 Git id/kind 资源和 Skill Link 的 skills、knowledge 两种类型。
- API 与真实本地 Git 仓库同时安装到 CAC；Git URL 通过测试环境重写到本地。
- 旧 resource.kind/name 与旧 id/version 兼容。
- 注册表路由、自动 W3 Token、精确版本、哈希及冻结锁文件回放。
- workspace.yml 优先于 apm.yml；未选中的无效 apm.yml 不被读取或覆盖。
- 无 workspace.yml 时正常使用 apm.yml；无效 workspace.yml 不触发回退或下载。
- 无 apm.yml 时，workspace.yml 可通过 --root 安装到另一目录。
- skills → knowledge 分类迁移：重投影、清理旧部署、冻结拒绝未同步变更。
- 删除包缓存和 CAC 输出后的冻结恢复；重复安装无重复接口下载。
- 锁文件完整字段往返、资源 ID 重复、同一 Git 目录重复投影校验。
- 按资源 ID 卸载，修改选中的清单，保留 Workspace 扩展元数据。
- 目标解析、作用域、项目生命周期、更新、事务回滚、并发锁、卸载原有行为。
- DME 完整示例成功解析 14 个资源，其中 4 个 Knowledge。

## 验证边界

HTTP 请求在测试中模拟，Git 使用本地测试仓库。未访问用户内网 API，
未使用真实账号、密码、APPKEY 或 Token。Windows EXE 需要在用户环境重新构建，
示例中的真实平台 ID、版本、Git 路径和 CAC 对知识目录的加载行为需现场核对。

## 测试命令

在 APM 仓库根目录，安装开发依赖后执行：

```bash
uv run pytest -q --disable-warnings \
  tests/unit/registry \
  tests/unit/deps/test_typed_resource.py \
  tests/unit/deps/test_lockfile_field_properties.py \
  tests/unit/deps/test_lockfile_consumer_contract.py \
  tests/unit/core/test_scope.py \
  tests/unit/core/test_target_resolution_v2.py \
  tests/unit/core/test_lifecycle_scripts.py \
  tests/unit/test_command_logger.py \
  tests/unit/commands/test_update_command.py \
  tests/unit/install/test_root_redirect.py \
  tests/unit/install/test_install_transaction.py \
  tests/unit/install/test_resolution_transactionality.py \
  tests/unit/install/test_architecture_invariants.py \
  tests/unit/install/test_registry_wiring.py \
  tests/unit/install/phases/test_read_yaml_targets_list_form.py \
  tests/unit/commands/compile/test_watch_target_forwarding.py \
  tests/unit/integration/test_scope_install_uninstall.py \
  tests/unit/test_uninstall_dev_dependencies.py \
  tests/unit/test_uninstall_engine_phase3w5.py \
  tests/unit/test_uninstall_transitive_cleanup.py \
  tests/unit/commands/test_uninstall_atomic_selection.py \
  tests/unit/test_uninstall_engine_helpers.py \
  tests/unit/models/test_dependency_uninstall_selection.py \
  tests/unit/test_uninstall_engine_validation.py \
  tests/unit/test_uninstall_reintegration.py \
  tests/unit/test_uninstall_shared_ownership.py \
  tests/unit/test_uninstall_shared_diamond_dependency.py
```

测试临时目录应位于源码仓库之外，以免测试的父目录查找意外找到仓库自身的 apm.yml。
Windows 上可在当前终端设置 TEMP/TMP 为专用测试目录；本次验证使用仓库之外的临时目录。
