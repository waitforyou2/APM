# 内置默认 Skill 下载源

适用于已安装自动获取 W3 Token 更新、且管理员已填写 `_skill_link_private.py` 的定制 APM。
该更新不修改私有配置文件，也不增加需要填写的配置项。

## 生效规则

| apm.yml 内容 | 行为 |
| --- | --- |
| 没有 `registries`，包含 `id + version` 资源 | 默认使用内置 `corp-skills`，协议为 `skill-link-v1`，URL 从私有配置的 `service_url` 读取 |
| 显式声明 `registries` | 沿用显式声明；下载时仍校验凭据与服务地址的绑定 |
| `git:` 资源 | 沿用 Git 下载 |
| 只有 Git 资源 | 不加载私有配置，不因本更新要求启用 registry 功能 |

内置默认适用于 `dependencies.apm` 和 `devDependencies.apm` 中的对象声明。
对象可省略 `registry`，也可明确写 `registry: corp-skills`。`alias`、`targets` 继续可用。
Git 字符串简写不会因为内置默认源而被改成接口资源。

**要启用默认值，请删除整个 `registries` 字段。** `registries: {}`、`registries: null` 都属于显式配置，不触发默认源；错误的显式声明也不会偷偷回退。
如果指定了其他 registry，必须按已有方式配置该源；名字拼写错误不会改走 `corp-skills`。

没有内置 `corp-skills` 配置的通用构建保留原行为，不会凭空选择一个服务地址。
显式 OpenAPM `$schema` 合约保持原有解析行为；定制 Skill Link 示例继续省略 `$schema`。

## 最小配置

```yaml
name: design-workspace
version: "0.1.0"
description: DME设计作业空间

targets:
  - cac

dependencies:
  apm:
    - id: frontend-design
      version: "0.0.1"
```

原有产品信息、workflow 顺序和资源关系字段可以继续保留。本更新只调整下载源默认值。
混合 Git 时，继续把原来的 `git` 资源放在同一个 `dependencies.apm` 列表中，不用更改其字段。

## 地址与认证

本机文件仍为：

```text
src/apm_cli/deps/registry/_skill_link_private.py
```

此次确认的 Skill 服务基地址为：

```text
https://apigw-cn-south02.huawei.com/api/mcpService
```

如果你已经在 `PROFILES["corp-skills"]["service_url"]` 中改好并验证成功，不需要再编辑。
默认路由直接读取这一个地址，不会使用旧的 `bzz.com` 常量；解析器中也没有第二份服务地址。
Token 接口仍由同一配置的 `token_url` 指定。
账号密码与请求头不放入 apm.yml，也不放入锁文件。

读取配置时只取得服务地址，不发起登录。实际需要下载链接时，仍按上一版流程取新 Token。
本地旧的 URL 绑定不会覆盖内置默认服务地址。
registry 实验功能开关保持原规则；已经启用的机器无需重复配置，新用户需执行一次：

```powershell
& $apm experimental enable registries
```

## 从现有 workspace 迁移

1. 在已验证自动 Token 的源码上应用增量补丁。
2. 保留你已填写的 `_skill_link_private.py`，不要用空模板覆盖。
3. 使用 `uv run pyinstaller --clean build/apm.spec --noconfirm` 重新打包。
4. 在 workspace 的 apm.yml 中删除整个 `registries` 字段，其余配置不变。
5. 使用新 EXE 安装。

如果原显式地址与内置地址一致，资源身份和锁文件条目保持一致，可以先验证：

```powershell
& $apm install --frozen --no-policy
```

然后验证真实自动登录与下载：

```powershell
& $apm install --refresh --no-policy
```

`--refresh` 仍校验固定 ID + version 对应的 ZIP 哈希，不会把内容变化当成正常更新。
不需要删除旧锁文件或已安装目录。
如果你更换了实际服务地址，冻结安装会识别到来源变化并拒绝沿用不匹配的锁定记录；应确认来源变更后再运行普通安装。

## 验证说明

测试覆盖省略配置、显式优先、Git 混合、开发依赖、地址读取、旧配置干扰、自动认证、冻结重装、来源变化及哈希保护。
真实 Windows EXE 需要在本机重建，内网接口仍由管理员环境联调。
