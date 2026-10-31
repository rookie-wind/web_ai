"""服务端转换执行能力：沙箱、校验、测试数据、报告、产物工具。

子包结构：
- sandbox_runner.py  子进程入口（stdin→stdout 协议，加载分发源镜像引擎）
- executor.py        沙箱调度（子进程 + 超时 + 上限 + 临时目录用后即清）
- validator.py       三契约结构校验（MQTT/HTTP/Modbus）
- testdata.py        测试输入生成（normal/boundary/abnormal）
- report_store.py    测试报告持久化（owner 隔离 + 短 TTL）
- conversion_tools.py 6 个 exec 类 MCP 工具注册
"""
