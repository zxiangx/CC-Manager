# Monitor 只读 SSH 代理设计

## 目标

让本机 Codex Monitor 在自身保持 `read-only` sandbox 的前提下，能够通过 CCM 后端检查预先配置的远端服务器状态。第一版服务于 `yc_h100`，并保持为可复用的多 profile 结构。

## 方案选择

采用“结构化操作代理”：Monitor 只调用 CCM MCP 工具，MCP 再访问 loopback API，CCM 后端持有 SSH 凭据并生成固定命令模板。相比直接给 Monitor SSH socket，这不会把私钥、任意网络或任意 shell 权限交给模型；相比关键字过滤任意命令，它能可靠阻止重定向、命令替换和写操作。

```text
Codex Monitor (read-only sandbox)
  -> ccm_monitor_agent.read_remote_status
  -> authenticated loopback API + exact turn generation
  -> configured profile + fixed read-only operation
  -> SSHExecutor(host, port, user, key, strict known_hosts)
  -> remote host
```

## 配置与权限边界

`CCM_MONITOR_SSH_PROFILES` 是 JSON 对象。每个 profile 明确给出 host、port、user、private key、known_hosts 和允许读取的远端根目录。profile 名称由后端白名单解析，Monitor 不能提交 hostname、port、username 或 key path。

支持的第一版操作为：连接概况、进程概况、GPU 状态、当前用户 Slurm 队列、指定数字 job id、日志尾部、文件状态、tmux session 列表以及指定 tmux pane 尾部。所有参数都有长度、字符集和数值范围限制；路径在远端通过 `realpath` 再与允许根目录比较，以阻止 `..` 和符号链接逃逸。

SSH 调用不提供 stdin、PTY、端口转发或后台执行。每次调用有短超时和输出上限。非 22 端口被显式传给 Paramiko；Monitor profile 强制拒绝未知 host key，不使用自动信任。

## 失败处理

配置缺失、profile 不存在、私钥/host key/认证永久失败会被标记为 capability failure，并终止当前 Monitor，避免继续生成重复检查。连接超时、拒绝连接和暂时不可达保留为可重试错误。非法操作或参数只拒绝本次调用，不终止 Monitor，使模型有机会修正参数。

现有 Monitor 进程级连续失败退避保持不变。新代理返回稳定错误码；MCP 工具在永久错误时调用受 generation fence 保护的失败回调。UI 因而能看到真实 `failed` 状态，而不是把“SSH 无权限”当成 success 清零。

## 验证

单元测试覆盖 profile 解析、自定义端口、严格 host key、命令/路径注入、远端 symlink 守卫、超时与输出上限。API 测试覆盖内部认证、Task/Monitor/generation 绑定、永久失败状态转换。MCP 和 prompt 快照测试确认新工具只对 Monitor 暴露。部署后用 `yc_h100` 执行 connection、Slurm 和 GPU 的真实只读 smoke test。
