"""Copy to src/apm_cli/deps/registry/_skill_link_private.py BEFORE building.

Fill the four blank values locally. Do not commit the copied file or send its
contents in chat. An EXE with embedded credentials is not a secret store.
"""

PROFILES = {
    "corp-skills": {
        # Trusted download-link service base, including the gateway prefix.
        "service_url": "https://apigw-cn-south02.bzz.com/api/mcpService",
        # Full token endpoint; this is a DIFFERENT service from service_url.
        "token_url": "https://apigw-cn-south.huawei.com/api/ssoproxysvr/v2/w3tokens",
        "hw_id": "",
        "hw_appkey": "",
        "account": "",
        "password": "",
    },
}
