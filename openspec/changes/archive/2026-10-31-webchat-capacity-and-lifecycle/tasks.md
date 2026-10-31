## 1. SSE 增量读取

- [x] 1.1 `event_store.py` 新增 `replay_with_offset` 与 `read_after_offset`，维护
  文件大小缓存；验证 pytest：建连偏移、只读新增、半行、缺失文件、after_seq 过滤。
- [x] 1.2 `sessions_api.py` SSE 改为增量循环，心跳按 15 秒重置，删除会话时终止流；
  验证 pytest 全量回归与实测轮询成本（105 ms → 0.002 ms）。

## 2. 容量与生命周期

- [x] 2.1 配置默认值：全局 100、单人 5、空闲 1800s、扫描 60s、并发轮次 16；
  验证 pytest：默认值断言。
- [x] 2.2 `runtime.py` 活动时间、空闲扫描、并发轮次计数；`api.py` 启动空闲扫描；
  验证 pytest：空闲回收（保留工作区、跳过执行中/近期活跃）、名额释放与超限拒绝。
- [x] 2.3 `sessions_api.py`/`artifacts.py` 在消息、租约、确认、SSE、上传下载刷新
  活动时间；`POST /messages` 超限返回 409；验证 pytest。

## 3. 账号与文档

- [x] 3.1 `accounts.py` 按 mtime 热加载；验证 pytest：新增账号即时可见、文件损坏
  即时进入配置错误。
- [x] 3.2 README 更新容量/账号/压测说明；新增 `webchat/tools/load_sse.py`。

## 4. 回归

- [x] 4.1 webchat 全量 pytest 全绿（154 passed）；主项目基线 770 passed, 1 skipped。
- [x] 4.2 `openspec validate --all --strict` 通过后归档本变更。
