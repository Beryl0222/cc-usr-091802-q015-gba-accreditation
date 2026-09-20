# 湾区参赛资格通行

用于协同粤港澳赛事名单、证件核验、例外复核和离线场馆通行的演示服务（纯标准库，无外部依赖）。

## 它解决什么问题

- 赛区发布**带生效期**的材料规则；评估只看当时生效的版本，已发生的入场保存版本快照，不随后续规则变化改写。
- 代表队反复换人：名单是**不可变版本流**，换人追加新版本；个人以稳定 `member_id` 跨版本携带材料与决定历史。
- 系统按**身份与职责**生成待核项：身份证件、比赛保险、反兴奋剂声明对所有随赛人员；反兴奋剂声明不含随队职员；监护同意仅对未成年运动员。
- 证件、保险、反兴奋剂、监护同意由**不同机构**分别核验；**原件仅向对应机构的授权审核岗开放**，场馆与接驳人员只能拿到通行结论（姓名、职责、可入场馆、到期时间）。
- 换人、续证、资格申诉、临时医疗豁免、两地冲突暂停/复核都进入**带依据的决定台账**（决定含理由、依据、作用、被取代的旧结论）。
- **两地结论冲突只暂停相关个人**，不扩大到全队，并自动作废其未使用凭证；仅指定复核人可作出权威结论解除暂停。
- 断网闸机用设备密钥本地验签 **HMAC 短期凭证**，恢复后上传签名回执；同一回执（及同一凭证同场馆的重复扫描）**幂等，只计一次通行**。
- 办赛人员赛前看到按紧迫程度排列的看板（冲突 → 已过期 → 被拒 → 缺件 → 审核中 → 赛中到期）；赛后可从一条入场记录查回**名单版本、规则版本、核验机构、例外决定与设备回执**。

## 运行

```bash
python3 service.py --check                      # 基础检查
python3 service.py --port 8000                  # 启动服务
python3 -m unittest discover -s tests -v        # 全部契约（23 项）
```

启动后 `GET /health` 返回项目标识。内存存储，重启即重置，便于演示。

## HTTP API

除 `/health` 外均需 `Authorization: Bearer <token>`（演示令牌见 `demo.py` 的 `TOKENS`）。

| 方法 & 路径 | 岗位 | 说明 |
| --- | --- | --- |
| `POST /admin/rules` | organizer | 赛区发布新版材料规则（生效起点、要求项与适用职责） |
| `GET /rules?zone=Guangdong[&at=...]` | 登录即可 | 查某时点生效的规则 |
| `POST /delegations/{id}/roster` | 本队 manager | 提交/换人，产生名单新版本 |
| `POST /members/{id}/documents` | 本队 manager | 提交材料（仅存摘要与到期日） |
| `GET /members/{id}/documents/{code}` | 负责该项目的 reviewer | 取原件摘要；其他机构/岗位一律拒绝 |
| `POST /verifications` | reviewer | 本机构核验结论（通过/不通过；续证再核验并声明 supersedes） |
| `GET /members/{id}/eligibility?event_id=...` | organizer / 发证岗 / 本队 | 个人资格结论与逐项状态 |
| `GET /events/{id}/dashboard` | organizer / 发证岗 | 按紧迫程度排列的缺件、到期、冲突 |
| `POST /appeals` | appeal_officer | 资格申诉裁决（通过须给有效期与证据） |
| `POST /exemptions` | medical_officer | 临时医疗豁免（如治疗用药豁免） |
| `POST /conflicts/resolve` | conflict_resolver | 两地冲突复核，解除或维持暂停 |
| `POST /passes` | pass_officer | 合格才签发短期 HMAC 通行凭证 |
| `GET /validate?token=...` | venue/gate 等 | 仅返回 GREEN/DENY 与最小通行信息 |
| `POST /gates/receipts` | gate_operator | 上传离线签名回执；重复上传去重 |
| `GET /entries/{id}/trace` | organizer | 入场追溯：规则/名单版本、机构核验、例外决定、设备回执 |

## 代码结构

- `accreditation.py` — 领域核心：规则版本、名单版本、核验、决定台账、资格评估、凭证、离线闸机、回执幂等、入场追溯。时钟可注入，便于确定性测试。
- `demo.py` — 虚构演示装配：三地五机构、岗位账号、一场赛事与一台闸机。
- `service.py` — HTTP API 与服务入口，负责认证、岗位授权与请求校验。
- `tests/` — 基础契约 + 19 项领域场景（冲突仅挂个人、规则不溯及既往、续证恢复、豁免到期、换人、离线重传一次、追溯不可变）+ 2 项 HTTP 全链路。
- `fixtures/sample.json` — 公开领域词汇（地区、职责、材料项、状态与紧迫度排序），不含真实个人资料或凭据。
