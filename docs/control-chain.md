# 可配置控制链

## 固化的两条语义

- **跨班/跨周期切换**：新版本发布后只更新 active 指针；已经启动的 `ChainRun` 继续引用启动时捕获的 `ChainRef`，下一个周期才使用新链。
- **历史保留**：所有校验通过并安装的链版本都完整保留；链定义、运行实例、审计流水统一引用 `name/version/fingerprint`。

版本指纹由链名、阶段顺序、阶段动作、必需阶段和先后关系规范化后计算。同一版本号但内容不同会被拒绝；重复安装同一版本不产生新版本。

## 配置

示例见 `configs/tunnel-control-chain.json`。

```bash
python3 -m tunnelnet --chain-config configs/tunnel-control-chain.json
```

装配时会拒绝：

- 必需阶段缺失
- 阶段重复
- 配置了运行时不支持的阶段
- `before` 引用未知阶段
- 阶段顺序不满足 `before`
- 先后关系成环

## API

- `GET /api/chain`：当前链及版本
- `GET /api/chain?version=<version>`：查看旧版本
- `GET /api/chain/versions`：全部历史版本
- `POST /api/chain/publish`：校验并安装新版本；`activate:false` 可只安装不切换
- `POST /api/chain/activate`：切换 active 指针，下一个周期生效
- `GET /api/chain/runs?version=<version>`：某版本的运行实例
- `GET /api/chain/runs/detail?id=<run_id>`：单实例的阶段轨迹
- `GET /api/chain/replay?version=<version>`：旧版本定义、实例和审计流水
