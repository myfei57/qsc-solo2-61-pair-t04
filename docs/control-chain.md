# 可配置控制链

阶段顺序不再写死在代码里。每个管廊提供一份 JSON 链定义，服务启动时**装配并校验**，
校验通过才冻结成一个带内容摘要的不可变**链版本**；链定义、运行实例、审计流水三方
通过同一个 `name@version` + `digest` 互相关联。

## 配置

最小配置只需要 `name`、`version`、`stages`；`required`、`predecessors`、`actions`
缺省时采用内建的入廊→审计默认值。示例见 `configs/example-chain.json`。

```bash
tunnelnet --store data --chain-config configs/example-chain.json
```

## 装配校验（失败即拒绝启动）

启动（以及每次发布）时按顺序收集全部错误，而不是一次报一个：

| 规则 | 错误码 |
| --- | --- |
| `required` 阶段缺失 | `missing_stage` |
| 阶段重复 | `duplicate_stage` |
| 依赖引用了不存在的阶段 | `unknown_stage` |
| 阶段出现在它必须先于的阶段之后 | `order_violation` |
| 阶段自环 | `self_loop` |
| 前驱图成环 | `cycle`（并给出环路径） |

内建安全不变量：`access`/`environment`/`fire`/`energy`/`audit` 必须存在；
`audit` 必须排在所有执行阶段之后（链必须以审计收尾）。

## 版本策略（已锁定）

1. **入链即冻结**：周期 `start_cycle` 时钉住当时激活版本的 `ChainRef`，并持久化实例。
   运行中发布/激活新链**不会撕开在跑周期**；新链只影响之后启动的周期。跨班切换因此
   有确定结果——交班时段在跑的周期按交班链跑完归档，接班后新周期才用新链。
2. **全量历史保留**：链版本只增不改不删。版本号相同但内容不同直接拒绝
   （必须升版本号）。旧版本可被回放随时查到。
3. **重复装配幂等**：同一版本重复发布返回 `published=false`，不产生重复文档。

## API

| 方法/路径 | 作用 |
| --- | --- |
| `GET /api/chain` | 当前激活链及其版本/摘要 |
| `GET /api/chain/versions` | 全部保留版本 + 激活指针 |
| `POST /api/chain/publish` | 装配并存储一个版本（**不**激活），校验失败返回 400 |
| `POST /api/chain/activate` | 激活；body 给 `config` 或已有 `chain_id` |
| `GET /api/chain/instances` | 周期实例及其钉住的链引用 |
| `GET /api/chain/replay?cycle_id=` | 把历史周期还原到它当时的链 |
| `GET /api/chain/replay?chain_id=` | 列出该版本下全部周期 |
| `GET /api/audit/query?chain_id=&cycle_id=` | 按链版本/周期过滤审计流水 |

`POST /api/cycle` 的响应新增 `chain`（版本引用）和 `cycle_id`；该周期产生的每条
审计记录都带 `chain_id`、`chain_digest`、`cycle_id`、`stage`。

## 存储

复用原子写 JSON 文档库：

* `chain/<name>@<version>.json` —— 不可变版本定义（含 digest）
* `chain_cursor/active.json` —— 当前激活指针
* `chain_instance/<cycle-id>.json` —— 周期实例（钉住的 ref、阶段、状态、结果）

重启后管理器从磁盘恢复激活版本与在跑实例；旧版本和旧实例都能继续回放。
