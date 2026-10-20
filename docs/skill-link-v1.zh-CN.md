# Skill Link v1 下载适配

需要管理员统一配置公共账号并自动获取 Token 时，使用 [自动认证说明](skill-link-auto-token.zh-CN.md)。
本页中的手动环境变量认证仍兼容；自动认证配置启用后按自动认证说明操作。

基于 `https://github.com/waitforyou2/APM`，开发基线为
`e4c02e2673b92d8bf885c107de594a64b7be5b03`。保留现有 Git 安装、typed resource、
knowledge/workflows 和 `.cac` target；新增 `skill-link-v1` provider。

## 1. 配置 apm.yml

完整示例见 `examples/skill-link/apm.yml`。API 来源最小配置：

```yaml
name: design-workspace
version: "0.1.0"
targets: [cac]

registries:
  corp-skills:
    provider: skill-link-v1
    url: https://你的服务域名
  default: corp-skills

dependencies:
  apm:
    - id: frontend-design
      version: "0.0.1"
```

`url` 是服务根地址（可带统一网关路径前缀），不要填写查询参数或 `/external/skills/link/v1/get`。
APM 会拼接该固定端点，用 GET 查询 `skillId` 和 `version`。可以配置多个命名服务，
在依赖中用 `registry: <名字>` 选择；声明默认服务后，Git 依赖请明确使用 `git:` 对象。
原生 APM Registry 继续使用 `{url: ...}`，不填写 `provider`。

依赖允许 `id`、`version`、`registry`、`alias`、`targets`。
`id` 和 `alias` 使用小写字母、数字、连字符，最多 64 字符，禁止 Windows 设备名。
`alias` 不填时等于 ID，控制 `.cac/skills/<alias>/` 的目录名；`SKILL.md` 内容保持原样。
版本必须是完整的固定版本，如 `0.0.1`、`1.0.0-beta.1`；不支持 `latest`、`^`、`~`、版本范围。
接口返回单个 Skill，所以不接受 `path`、`skills` 子集或 `resource`。
Workspace 的关系字段引用 `alias`（不填写 alias 则引用 id）。

这是此定制分支的扩展，不是 OpenAPM 标准协议。请使用现有不带 `$schema` 的 apm.yml；
不要给它声明 OpenAPM v0.1 的 `$schema`。可以保留自己的 `schemaVersion` 元数据。
provider 必须声明在项目的 apm.yml；本机配置只用于绑定凭据和 URL。

## 2. 本机认证（PowerShell）

先准备打包后的 APM，或把下文的 `& $apm` 换为 `uv run apm`：

```powershell
$apm = "D:\APM\dist\apm\apm.exe"
& $apm experimental enable registries
& $apm config set registry.corp-skills.url "https://你的服务域名"
```

该 URL 与项目配置一致，表示本机信任向这个服务发送名为 `corp-skills` 的凭据。
项目 YAML 改到其他地址时，不会自动把原凭据发过去。

三个请求头从当前进程的环境变量读取，避免写入代码、apm.yml、lock 或 EXE。
使用以下提示输入，输入内容不会出现在 PowerShell 历史命令中：

```powershell
function Set-SessionSecret([string]$Name, [string]$Prompt) {
    $secureValue = Read-Host $Prompt -AsSecureString
    $credential = New-Object System.Management.Automation.PSCredential("unused", $secureValue)
    [Environment]::SetEnvironmentVariable($Name, $credential.GetNetworkCredential().Password, "Process")
}
Set-SessionSecret "APM_REGISTRY_HW_ID_CORP_SKILLS" "X-HW-ID"
Set-SessionSecret "APM_REGISTRY_HW_APPKEY_CORP_SKILLS" "X-HW-APPKEY"
Set-SessionSecret "APM_REGISTRY_AUTH_TOKEN_CORP_SKILLS" "X-AUTH-TOKEN"
```

认证变量后缀来自 registry 名称：大写，`-`/`.` 换成 `_`。
认证值由调用者提供/更新，本版本不自动登录或刷新 X-AUTH-TOKEN。
环境变量仍能被有本机进程访问权限的人读取，EXE 打包也不会让内嵌密钥变成秘密。

服务收到：

```http
GET /external/skills/link/v1/get?skillId=frontend-design&version=0.0.1
Content-Type: application/json
X-HW-ID: <环境变量>
X-HW-APPKEY: <环境变量>
X-AUTH-TOKEN: <环境变量>
```

响应要求 HTTP 200，且 JSON 的整数 `code` 为 200，`data.downloadUrl` 为 HTTPS URL。
第二次请求下载 ZIP，不携带上述三个认证头、API Cookie、netrc 认证或 Authorization。
API 跳转拒绝；ZIP 支持有限次 HTTPS 跳转。ZIP 返回 401/403 时重新获取一次下载链接。
错误消息不打印响应体、密钥或带签名的 URL。

## 3. 安装与锁定

```powershell
cd D:\你的workspace
$env:APM_CACHE_DIR = "D:\apm-cache"
& $apm install --no-policy
```

`--no-policy` 沿用你本次本地验证时的用法，可以避免父仓库 GitHub 组织策略探测；
有组织策略要求的环境按实际配置运行。

支持两种 ZIP 布局：根目录直接含 `SKILL.md`，或唯一顶层目录内含 `SKILL.md`。
不会递归猜测任意深度的 Skill 根。拒绝多个顶层候选、目录穿越、符号链接和 Windows 路径冲突。
ZIP 下载上限 128 MiB；沿用公共解压器的 10,000 条目 / 512 MiB 解压大小上限。
不要在包中加 apm.yml/.apm 包装层；适配器会生成这层安装元数据。

安装结果：

- `apm_modules/<alias>/`：供 APM 维护的规范化包。
- `.cac/skills/<alias>/SKILL.md` 及原始附件：分发结果。
- `apm.lock.yaml`：保存固定版本、稳定的接口定位 URL、`skill_link_url` 和 ZIP SHA-256。

用户承诺相同 ID + version 的 ZIP 字节不变。首次下载由本机计算 SHA-256 建立基线；
接口没有发布方摘要/签名，因此首次哈希并不是对发布方真实性的独立验证。
之后重新下载会重新向 API 取链接，用 lock 中的哈希验证内容。
同 ID/版本的 `--refresh` 也不允许静默替换哈希；真正修改内容请发布新版本。
新版本需修改 apm.yml 的 `version` 后正常安装，再提交更新后的 lock。

```powershell
& $apm install --frozen --no-policy
```

已有安装会复用本地内容；清空本地安装目录后，`--frozen` 可联网获取同版本的新下载链接。
它不会选择更新版本。清除缓存后重装仍需网络和有效认证。
旧版 APM 不认识此 provider，请让团队统一升级；不要混用新旧二进制管理同一个 workspace。
由于接口没有版本列表和发布 API，`outdated` 显示未知，`publish` 明确拒绝该 provider。

## 4. 在 Windows 构建 EXE

在应用补丁后的 APM 仓库根目录执行。继续使用你已经跑通的 Python 3.12 / uv 环境：

```powershell
uv sync --frozen --extra build --python 3.12
uv run pyinstaller build/apm.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "APM build failed" }
.\dist\apm\apm.exe --version
```

这里直接使用仓库的 PyInstaller spec，避开你之前在 Windows PowerShell 5.1 遇到的
`RuntimeInformation.ProcessArchitecture` 检测问题。产物目录是 `dist\apm`，
发给同事时压缩整个目录，不能只发送 `apm.exe`。此操作在 Windows 上完成；本次没有生成或验证 Windows EXE。
Git 来源仍要求使用者环境能够执行 Git 并访问其代码仓。

如企业证书导致 Python HTTPS 校验失败，配置含企业 CA 的 PEM bundle，例如：

```powershell
$env:REQUESTS_CA_BUNDLE = "D:\certs\company-ca-bundle.pem"
```

不要关闭 TLS 校验。该变量针对新适配器的 Python HTTPS 请求；Git 和 uv 的证书信任仍分别配置。

## 5. 验证范围

仓库测试使用模拟 HTTPS 响应、真实本地 Git 仓库和真实 APM CLI。
覆盖混合安装、`.cac` 分发、重复安装、冻结重装、alias 改名、锁版本不匹配、
同版本内容变化时失败且保留原 lock/分发文件、认证头隔离、签名链接续取和 ZIP 路径校验。
真实接口 URL/认证未提供，内网服务联调与 Windows EXE 运行需要在你的环境完成。

```powershell
uv run --extra dev pytest tests/unit/registry/test_skill_link.py -q
```
