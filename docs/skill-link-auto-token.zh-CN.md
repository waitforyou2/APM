# Skill Link 自动获取 W3 Token

这是已经跑通的 `skill-link-v1` 下载方式的增量更新，Git 下载、资源关系、锁文件和 `.cac` 分发继续使用原流程。
apm.yml 无需添加账号、密码、请求头或登录接口字段。

安装默认下载源更新后，`registries` 也可以省略，详见 [内置默认下载源](skill-link-builtin-registry.zh-CN.md)。

## 请求流程

每次确实需要调用下载链接接口时，按以下顺序执行：

1. POST 管理员配置的 `token_url`。请求头带 `Content-Type: application/json`、`X-HW-ID` 和 `X-HW-APPKEY`，JSON 请求体为 `account`、`password`。
2. 要求 HTTP 200 且响应 `status` 为 `ok`，读取 `result.newToken`。
3. GET Skill 下载链接接口。使用固定的 `X-HW-ID`、`X-HW-APPKEY` 和刚取得的 `X-AUTH-TOKEN`。
4. GET ZIP 下载地址。此请求不携带公共账号、密码、上述请求头、认证 Cookie 或 Authorization。

Token 不写入 apm.yml、lock、用户配置或日志，也不跨调用缓存。
如果签名 ZIP 地址过期，已有的一次续取机会也会先重新获取 Token。
Token 接口失败立即停止；不会自动重复登录，也不会回退到过期的环境变量 Token。
`result.token` 不用于回退，避免误用旧 Token；接口应按已提供的协议返回 `result.newToken`。
如果安装复用本地包、完全不调用下载链接接口，则无需登录。

## 管理员在哪里填写固定值

真实值只在你的开发机填写，无需发送给开发协作者或最终用户。
进入已经应用增量补丁的 APM 源码根目录，创建本机私有配置：

```powershell
cd "D:\coding\APM穿刺验证\APM"

$privateFile = ".\src\apm_cli\deps\registry\_skill_link_private.py"
if (-not (Test-Path -LiteralPath $privateFile)) {
    Copy-Item .\examples\skill-link\skill_link_private.example.py $privateFile
}
notepad $privateFile
```

文件内容如下。只需在本机填好四个空字符串：

```python
PROFILES = {
    "corp-skills": {
        "service_url": "https://apigw-cn-south02.huawei.com/api/mcpService",
        "token_url": "https://apigw-cn-south.huawei.com/api/ssoproxysvr/v2/w3tokens",
        "hw_id": "",
        "hw_appkey": "",
        "account": "",
        "password": "",
    },
}
```

| 配置字段 | 用途 |
| --- | --- |
| `service_url` | 可信的 Skill 下载链接服务基地址，包含 `/api/mcpService` |
| `token_url` | 获取 Token 的完整 POST 接口地址 |
| `hw_id` | 两个 API 共同使用的 `X-HW-ID` |
| `hw_appkey` | 两个 API 共同使用的 `X-HW-APPKEY` |
| `account` | 获取 Token 的公共账号 |
| `password` | 获取 Token 的公共账号密码 |

两个服务域名不同，按上面分别配置；不要把 `token_url` 填进 apm.yml 的 registry URL。
Python 字符串中的 `#` 不需要转义；若实际值含双引号或反斜杠，请按 Python 字符串规则转义。
配置保存为 UTF-8。空值、语法错误和不匹配的服务地址都会在发请求前报错。

`_skill_link_private.py` 已加入 `.gitignore`，不应提交到公共仓库。
PyInstaller 会在它存在时把它包含到构建中。更改这些固定值后需要重新打包。
构建产物仍是 onedir：分发整个 `dist\apm` 目录。

**内置凭据只省去用户填写，不能保密。** 有 EXE 的用户仍可能提取这些值。
如果要求最终用户无法获取公共账号和 APPKEY，应由服务端代理持有它们；客户端应使用用户自己的身份访问代理。

## 检查配置并打包

下面的检查只验证私有配置能否正确加载，不发起网络请求，也不输出凭据：

```powershell
uv run python -c "from apm_cli.deps.registry.skill_link_auth import get_w3_profile; p=get_w3_profile('corp-skills', 'https://apigw-cn-south02.huawei.com/api/mcpService'); assert p is not None, 'Private profile is missing'; print('Automatic token profile: OK')"
```

看到 `Automatic token profile: OK` 后执行：

```powershell
& {
    uv run pyinstaller --clean build/apm.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "APM build failed" }
    .\dist\apm\apm.exe --version
}
```

版本号仍是 `0.32.0`。本更新不会改动你先前修改过的 `scripts/windows/build-binary.ps1`。

## 在已验证的 workspace 中测试

请使用含最新私有配置的新 EXE。在你已有的测试 workspace 中执行：

```powershell
$apm = "D:\coding\APM穿刺验证\APM\dist\apm\apm.exe"
Set-Location "D:\apm-api-test-20261020-115346"
& $apm install --refresh --no-policy
```

这里加 `--refresh`，以便确实重新调用接口并验证自动登录；后续正常安装用 `install` 即可。
固定 ID + version 仍必须返回相同 ZIP 字节。现有锁文件哈希会在刷新时继续校验。
账号或 Token 响应出错、哈希不一致时，已有锁文件和分发内容由原安装事务保护。

有有效内置配置时：

- 用户不需要配置 `APM_REGISTRY_HW_ID_*`、`APM_REGISTRY_HW_APPKEY_*`、`APM_REGISTRY_AUTH_TOKEN_*`。
- 管理员配置优先；遗留环境变量中的旧值不会覆盖它。
- 内置 `service_url` 就是该凭据的可信绑定，不要求用户另行执行 `config set registry...url`。
- registry 名称须与内置 `corp-skills` 一致，服务基地址也须一致；不一致时停止，不把凭据发到其他地址。
- 新同事首次使用仍需执行一次 `apm experimental enable registries`，沿用原功能开关。

未内置该 registry 的配置时，仍保持上一版手动环境变量认证和本机 URL 绑定方式。
企业 CA、代理等配置也保持原方式，不关闭 TLS 校验。

## 验证范围

自动认证测试使用模拟 HTTPS 响应，检查真实 requests 构造的 POST/GET 请求、JSON 密码字符、Token 更新、认证信息隔离和失败场景。
完整 CLI 测试覆盖自动认证下的 Git + API 混合安装、复用、冻结重装、改名及哈希异常时的回滚。
没有使用真实公共账号、真实 APPKEY 或用户贴出的 Token 进行测试。
真实内网 SSO、公共账号权限、企业证书，以及 Windows 构建后的 EXE 仍需在管理员环境联调。

```powershell
uv run --extra dev pytest tests/unit/registry/test_skill_link.py tests/unit/registry/test_skill_link_auto_token.py -q
```
