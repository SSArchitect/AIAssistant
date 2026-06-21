# Server Deployment Runbook

最后更新：2026-06-21

这份文档记录把 Agent Assistant 推送到服务器的标准流程和已踩过的坑。目标是让后续部署只做可重复动作，不把运行期数据、API key 或 Nginx/systemd 配置搞丢。

## 1. 当前生产信息

```text
Server:      ubuntu@49.235.143.82
Public URL:  http://49.235.143.82/
Repo:        git@github.com:SSArchitect/AIAssistant.git
Server dir:  /home/ubuntu/agent_assistant
Deploy user: ubuntu
```

服务拓扑：

```text
Browser
  -> Nginx :80
      -> Go Gateway :8080
          -> Python Agent :9090
```

systemd 服务：

```bash
agent-assistant-agent.service
agent-assistant-gateway.service
nginx
```

运行期数据和配置在服务器本地保存，不随 Git 覆盖：

```text
/home/ubuntu/agent_assistant/data/assistant.db
/home/ubuntu/agent_assistant/data/agent_memory.json
/home/ubuntu/agent_assistant/logs/
```

## 2. 部署前本地检查

确认工作区只包含本次要推送的改动：

```bash
git status --short --branch
git diff --stat
```

跑完整检查：

```bash
./scripts/test.sh
```

敏感信息扫描。命中测试里的 `sk-test`、注释或 placeholder 可以接受；真实 key 不应该出现在 Git diff 里。

```bash
rg -n "sk-[A-Za-z0-9]|MINIMAX_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|DOUBAO_API_KEY|DEEPSEEK_API_KEY|api_key[:=][[:space:]]*['\"][^'\"]{12,}" \
  -g '!data/**' -g '!logs/**' -g '!tmp/**' -g '!*.db'
```

提交并推 GitHub：

```bash
git add <changed-files>
git commit -m "<message>"
GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new' git push
```

## 3. 标准服务器部署

服务器上有部署脚本：

```bash
ssh ubuntu@49.235.143.82 /home/ubuntu/deploy_agent_assistant.sh
```

脚本会做这些事：

```text
git fetch/reset 到 origin/main
创建/复用 .venv
安装 Python 依赖和 uv
go mod download
go build gateway
重启 Agent 和 Gateway
检查 9090 / 8080 health
```

如果这条能跑通，优先用它。

## 4. GitHub Fetch 失败时的兜底部署

腾讯云服务器偶发访问 GitHub HTTPS 失败，例如：

```text
GnuTLS recv error (-110): The TLS connection was non-properly terminated
```

这时不要改 remote，也不要用 `rsync --delete` 粗暴覆盖。用 Git bundle 通过 SSH 传 Git 对象：

```bash
commit=$(git rev-parse --short HEAD)
bundle="/tmp/agent_assistant_${commit}.bundle"

git bundle create "$bundle" main
scp "$bundle" ubuntu@49.235.143.82:/tmp/agent_assistant_update.bundle

ssh ubuntu@49.235.143.82 'bash -s' <<'EOF'
set -euo pipefail
cd /home/ubuntu/agent_assistant
git fetch /tmp/agent_assistant_update.bundle main:refs/remotes/origin/main
git checkout main
git reset --hard origin/main
git rev-parse --short HEAD

mkdir -p data logs .pids
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r agent/requirements.txt >/dev/null
python -m pip install uv >/dev/null

cd gateway
go env -w GOPROXY=https://goproxy.cn,direct GOSUMDB=sum.golang.google.cn
go mod download
go build -o gateway ./cmd/server/
cd ..

sudo systemctl restart agent-assistant-agent.service
for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:9090/agent/health >/dev/null && break
  sleep 1
  if [ "$i" = "30" ]; then
    sudo journalctl -u agent-assistant-agent.service -n 100 --no-pager
    exit 1
  fi
done

sudo systemctl restart agent-assistant-gateway.service
for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8080/api/health >/dev/null && break
  sleep 1
  if [ "$i" = "30" ]; then
    sudo journalctl -u agent-assistant-gateway.service -n 100 --no-pager
    exit 1
  fi
done

curl -fsS http://127.0.0.1:8080/api/health
EOF

rm -f "$bundle"
ssh ubuntu@49.235.143.82 'rm -f /tmp/agent_assistant_update.bundle'
```

## 5. 部署后验证

服务器状态：

```bash
ssh ubuntu@49.235.143.82 '
cd /home/ubuntu/agent_assistant &&
git rev-parse --short HEAD &&
git status --short --branch &&
systemctl is-active agent-assistant-agent.service agent-assistant-gateway.service nginx
'
```

公网健康检查：

```bash
curl -fsS http://49.235.143.82/api/health
curl -fsSI http://49.235.143.82/ | sed -n '1,12p'
```

模型配置检查，API key 只看是否存在，不要打印真实值：

```bash
curl -sS http://49.235.143.82/api/admin/settings | python3 -c '
import json, sys
data=json.load(sys.stdin).get("settings",{})
print("provider=" + data.get("llm.default_provider", ""))
print("minimax_key=" + ("SET" if data.get("llm.minimax.api_key") else "EMPTY"))
print("model=" + data.get("llm.minimax.model", ""))
'
```

真实聊天 smoke test：

```bash
conv=$(curl -sS -X POST http://49.235.143.82/api/conversations \
  -H 'Content-Type: application/json' \
  -d '{"title":"deploy smoke"}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')

curl -sS --max-time 90 -X POST http://49.235.143.82/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"conversation_id\":\"$conv\",\"query\":\"你好，回复两个字：正常\",\"agent_id\":\"general_assistant\",\"stream\":false}" |
  python3 -c 'import sys; print(sys.stdin.read()[:1200])'
```

Search smoke test：

```bash
ssh ubuntu@49.235.143.82 "
curl -sS --max-time 25 -X POST http://127.0.0.1:9090/agent/search \
  -H 'Content-Type: application/json' \
  --data-binary '{\"query\":\"炝锅面 大厨 教程\",\"sources\":[\"web\"],\"limit\":5}' |
  /home/ubuntu/agent_assistant/.venv/bin/python -m json.tool |
  sed -n '1,120p'
"
```

Pulse smoke test：

```bash
curl -fsS http://49.235.143.82/api/pulse | python3 -c '
import json,sys
data=json.load(sys.stdin)
print("date=" + str(data.get("date")))
print("topics=" + str(len(data.get("topics",[]))))
print("modules=" + str(len(data.get("modules",[]))))
print("items=" + str(sum(len(m.get("items",[])) for m in data.get("modules",[]))))
'
```

## 6. 运行期配置同步

代码配置在：

```text
config/config.yaml
```

运行期 Admin settings 在：

```text
data/assistant.db
```

Gateway 启动后会把数据库里的 settings 同步到 Python Agent。实际生效值优先看：

```bash
ssh ubuntu@49.235.143.82 '
cd /home/ubuntu/agent_assistant
. .venv/bin/activate
python - <<'"'"'PY'"'"'
import sqlite3
from agent.config import runtime_config
from agent.search.service import SearchService
conn=sqlite3.connect("data/assistant.db")
runtime_config.update(dict(conn.execute("select key,value from settings").fetchall()))
service=SearchService.from_runtime_config()
print("providers=" + ",".join(service.provider_names))
print("retry_attempts=" + str(service._retry_attempts))
print("retry_delay=" + str(service._retry_delay))
for provider in service._providers:
    if provider.name == "minimax-mcp":
        print("minimax_command=" + str(provider._command))
        print("minimax_resolved=" + str(provider._resolve_command()))
        print("minimax_timeout=" + str(provider._timeout))
PY
'
```

当前已知差异：

```text
local search.minimax.command:  /opt/homebrew/bin/uvx
server search.minimax.command: uvx
server resolved command:       /home/ubuntu/agent_assistant/.venv/bin/uvx
```

这是正常差异。不要把本地 Homebrew 绝对路径写回服务器。

## 7. 常见坑

### 7.1 页面正常但聊天报 Connection error

看 Agent 日志：

```bash
ssh ubuntu@49.235.143.82 'sudo journalctl -u agent-assistant-agent.service -n 100 --no-pager'
```

如果看到：

```text
Illegal header value b'Bearer '
```

说明服务器没有模型 API key，或者 Gateway 没有把 Admin settings 同步到 Agent。处理：

```bash
curl -sS http://49.235.143.82/api/admin/settings
sudo systemctl restart agent-assistant-agent.service agent-assistant-gateway.service
```

必要时从本地 `data/assistant.db` 同步 settings 表，但不要打印真实 key。

### 7.2 Search trace 里显示 `Search failed: web:`

历史原因：模型会传 `sources: "web"`，旧逻辑只匹配名为 `web` 的 provider，没有走 `bing-rss/minimax-mcp`。已在 `6181edb` 修复：`web` 表示通用网络搜索别名。

排查时看：

```bash
curl -sS 'http://49.235.143.82/api/runs/<run_id>?user_id=<user_id>'
sudo journalctl -u agent-assistant-agent.service -n 200 --no-pager
```

### 7.3 Pulse 刷新后为空，或会话内容看起来消失

先确认不是服务卡死：

```bash
ssh ubuntu@49.235.143.82 '
curl -fsS http://127.0.0.1:8080/api/health
systemctl is-active agent-assistant-agent.service agent-assistant-gateway.service nginx
'
```

然后看最近日志里是否有危险操作或长请求断开：

```bash
ssh ubuntu@49.235.143.82 '
journalctl -u agent-assistant-agent.service -u agent-assistant-gateway.service --since "2 hours ago" --no-pager |
  grep -E "DELETE +\"/api/(pulse/topics|conversations)|POST +\"/api/pulse/refresh|broken pipe|connection reset"
'
```

判断要点：

- `POST "/api/pulse/refresh"` 跑几分钟后出现 `broken pipe`，通常是浏览器刷新/超时断开，不等于服务挂了。
- `DELETE "/api/pulse/topics/<id>"` 表示订阅主题被删除；刷新接口本身不应该删除 topic。
- `DELETE "/api/conversations/<id>"` 会硬删除会话及消息，所以 assistant 内容会一起消失。
- 会话和 Pulse 都按 `user_id` 隔离；切换帐号后旧数据可能还在默认帐号 `0` 下，只是当前帐号看不到。

只查数量和归属，不要打印 settings/API key：

```bash
ssh ubuntu@49.235.143.82 'cd /home/ubuntu/agent_assistant && . .venv/bin/activate && python - <<'"'"'PY'"'"'
import sqlite3
conn=sqlite3.connect("data/assistant.db")
conn.row_factory=sqlite3.Row
for title, query in [
    ("accounts", "select id,name,updated_at from accounts order by updated_at desc"),
    ("conversations_by_user", "select user_id,count(*) as count,max(updated_at) as latest from conversations group by user_id order by latest desc"),
    ("messages_by_user_role", "select user_id,role,count(*) as count,max(created_at) as latest from messages group by user_id,role order by latest desc"),
    ("pulse_topics_by_user", "select user_id,count(*) as count,group_concat(name, ' | ') as topics from pulse_topics group by user_id"),
    ("pulse_items_by_user", "select user_id,date,source,count(*) as count,max(updated_at) as latest from pulse_items group by user_id,date,source order by latest desc"),
]:
    print("\\n" + title)
    for row in conn.execute(query):
        print(dict(row))
PY'
```

### 7.4 Nginx 返回默认页或旧服务

确认实际加载配置：

```bash
ssh ubuntu@49.235.143.82 'sudo nginx -T 2>/dev/null | grep -n -A25 -B4 "agent_assistant\\|default_server\\|sites-enabled"'
```

当前应由 `/etc/nginx/conf.d/agent_assistant.conf` 代理到 `127.0.0.1:8080`。历史上服务器有 `quant-internet` 站点代理到 `127.0.0.1:9930`，不要误判为新 Gateway。

### 7.5 Go toolchain 下载慢或超时

服务器会用 Go 1.24.x toolchain。首次构建可能慢。设置国内代理：

```bash
cd /home/ubuntu/agent_assistant/gateway
go env -w GOPROXY=https://goproxy.cn,direct GOSUMDB=sum.golang.google.cn
go mod download
go build -o gateway ./cmd/server/
```

### 7.6 不要覆盖运行期数据

不要对服务器目录做这种操作：

```bash
rsync --delete ./ ubuntu@49.235.143.82:/home/ubuntu/agent_assistant/
```

除非明确排除：

```text
.git/
.venv/
data/
logs/
.pids/
tmp/
.env
*.env
gateway/gateway
```

推荐优先 Git pull 或 Git bundle。

## 8. 快速回滚

如果新版本上线后异常，先看最近提交：

```bash
ssh ubuntu@49.235.143.82 '
cd /home/ubuntu/agent_assistant &&
git log --oneline -5
'
```

回滚到上一个稳定提交：

```bash
ssh ubuntu@49.235.143.82 '
set -e
cd /home/ubuntu/agent_assistant
git reset --hard <stable_commit>
cd gateway
go build -o gateway ./cmd/server/
cd ..
sudo systemctl restart agent-assistant-agent.service agent-assistant-gateway.service
curl -fsS http://127.0.0.1:8080/api/health
'
```

回滚不会恢复数据库内容；如数据库迁移有风险，先备份 `data/assistant.db`。
