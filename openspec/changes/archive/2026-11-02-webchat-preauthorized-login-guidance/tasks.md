## 1. 提示与技能对齐

- [x] 1.1 `adapter.py` 系统提示增加：Web 会话已由服务端内置账号完成 login
  激活；不得调用 login、不得索要手机号/验证码；认证失效时如实告知。
- [x] 1.2 `xlpa/SKILL.md` 增加 Web 会话例外段落（跳过业务 Token 检查与登录）。
- [x] 1.3 `modbus-conversion/SKILL.md` 增加 Web 会话例外段落（跳过手机号/
  验证码与 login 调用）。
- [x] 1.4 README 增加“平台登录与预激活”说明。

## 2. 验证

- [x] 2.1 单测断言系统提示包含预激活与禁止 login 文案。
- [x] 2.2 webchat 全量：**183 passed, 0 failed**。
- [x] 2.3 `openspec validate --all --strict` 通过后归档。
