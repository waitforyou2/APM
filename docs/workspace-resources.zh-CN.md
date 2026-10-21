# Workspace 资源声明与项目入口

本次扩展用于 Workspace 的安装与维护。完整示例位于
`examples/dme-workspace/workspace.yml`，包含 7 个 Skill、4 个 Knowledge、2 个 Agent、1 个 Workflow。
示例接口 ID 和版本、根据目录结构推导的 Agent/Workflow Git 路径需管理员核对。

## 项目配置文件

项目消费流程按以下顺序选择一个文件：

1. 存在 `workspace.yml`：只使用它，不与 `apm.yml` 合并。
2. 不存在 `workspace.yml`：沿用 `apm.yml`。
3. `workspace.yml` 存在但无效、不可读或不是文件：报错，不回退。

两个文件的内容格式相同。无需生成中间 apm.yml，也无需重命名文件。
安装、冻结安装、刷新、目标读取、策略读取、项目生命周期脚本、更新和卸载读取选中的文件。
卸载等配置写入也使用该文件，保留产品、关系和工作流顺序等扩展字段。
支持 `apm install --root <目录>`：从调用位置选取配置，将资源和锁文件写入指定目录。
锁文件仍叫 `apm.lock.yaml`，包缓存仍在 `apm_modules/`，CAC 分发路径不变。

仅新增 `workspace.yml` 这个精确文件名，不增加 `workspace.yaml` 别名。
用户级 `apm install -g` 的入口以及依赖包内部/生成的包清单继续使用 apm.yml。
包发布、打包、Marketplace 制作等生产端格式不在这次入口扩展范围内。

## 统一资源声明

接口资源：

```yaml
dependencies:
  apm:
    - id: bmad-create-prd
      kind: skills
      version: "0.0.1"
    - id: reliability-requirement-knowledge
      kind: knowledge
      version: "0.0.1"
```

Git 资源：

```yaml
dependencies:
  apm:
    - id: java-sdk
      kind: knowledge
      git: https://codehub.example.com/team/assets.git
      ref: main
      path: knowledge/java-sdk
```

`id` 是关系引用和安装命名的标识。接口来源同时将其作为请求参数 `skillId`。
在包含新格式的清单中，各显式资源 ID 必须全局唯一，包含 dependencies 和 devDependencies。
同一个 Git 来源目录只注册一次，通过关系复用；不能给它两个 ID 来要求不同的投影。
ID 使用小写字母、数字、连字符，最长 64 字符，不使用 Windows 设备保留名。

`kind` 支持 skills、agents、knowledge、workflows。
新格式不再要求 name、alias 或 resource 包装。如果额外填写 alias，它必须与 id 一致；
不允许同时填写新式 kind 和旧式 resource，避免出现两套互相矛盾的分类。

有 git 的资源由 Git 下载器处理，必须有目录 path，版本用 ref；
API 资源用精确 version，由显式 registries 或工具内置的 corp-skills 路由。
新格式 Git 条目不会因为包含 id 而走 Registry，也不会触发读取内置认证配置。
当前 skill-link-v1 提供者允许 skills 和 knowledge，尚不提供 agents/workflows API。
现有 experimental registries 开关和认证绑定机制保持不变。

## Knowledge 的下载与分发

API 来源的 Knowledge 仍调用 Skill 链接接口，并继续在每次链接请求前取得 W3 Token。
该接口的 ZIP 格式要求不变：根目录或唯一顶层目录包含 SKILL.md。
下载器验证哈希并解压后，将原始文件内容按 knowledge 类型部署：

```text
.cac/knowledge/<id>/SKILL.md
.cac/knowledge/<id>/references/...
```

Git 来源的 Knowledge 可以来自普通资料目录，也可以来自带 SKILL.md 的目录；无需改远程目录名。
APM 不会改写文档内容或将 Skill 语义转换成别的知识协议。CAC 如何加载这些知识，由其运行时决定。
Agent 延续原有展平策略，部署到 `.cac/agents/<id>.md`。

改变 kind 会使旧投影失效并重新分发，即使 id、version 或 Git 提交未改变。
锁文件记录资源类型，冻结安装会拒绝尚未同步的分类变更。
原有文件所有权、用户修改保护和相同版本 ZIP 哈希校验规则继续适用。

## 使用关系

`relations`、`workflowSequence`、`product` 等是 Workspace 使用系统的元数据。
示例采用 Workflow → Agent → Skill → Knowledge 的常见关系，但 APM 不强制层级、
不执行工作流、不依据这些关系做权限控制，也不检查这些关系的完整性。
安装会下载 dependencies 中声明的全部资源，不通过关系做裁剪。
引用使用 id；改 ID 后，管理员应同步调整关系引用。
卸载资源保留原有关系元数据，管理员应同时清理不再需要的引用。

## 兼容与本地使用

旧 Git 资源的 `resource: {kind, name}` 及旧接口 `id + version` 继续可用。
未写 kind 的旧接口条目仍按 skills 处理。
显式新格式条目在序列化时保留 id/kind，不重新添加 name 或 alias。
锁文件可包含内部 resource.kind/name 和 compact_resource 标记；它是生成文件，无需手改。

应用源码补丁后，需要重新构建 EXE：

```powershell
cd "D:\coding\APM穿刺验证\APM"
uv sync --frozen --extra build --python 3.12
if ($LASTEXITCODE -ne 0) { throw "Dependency sync failed" }
uv run pyinstaller --clean build/apm.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "APM build failed" }
.\dist\apm\apm.exe --version
```

保留已有 `src/apm_cli/deps/registry/_skill_link_private.py`，本补丁不更改它。
将示例修改为真实资源后保存为 Workspace 根目录的 workspace.yml，然后执行：

```powershell
& "D:\coding\APM穿刺验证\APM\dist\apm\apm.exe" install --no-policy
```

不要将上面的构建目录误当成 Workspace 目录。安装命令在 workspace.yml 所在目录运行。
新增版本仍显示 APM 0.32.0；是否应用本功能应以补丁提交和新格式安装结果判断。
