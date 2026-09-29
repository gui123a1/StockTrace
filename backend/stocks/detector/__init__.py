"""探测器：平静盘面下的渐进微变监测（独立一级功能模块）。

模块划分（对齐 market/ 包的分层习惯）：
- registry    维度注册表：定义、默认参数、启停与原因（单一事实来源）
- dimensions  数学工具 + 各对象序列构建 + 维度计算实现
- calm        平静状态判定（进入监测的前提，不满足则跳过该对象）
- signals     同向投票、周期维持、严重程度分级与信号落库
- review      5 个交易日回看命中率 → 权重/阈值有界迭代（流水进 DetectorRun）
- scan        一次完整扫描的编排（守卫、降级记录、幂等、清理）
- views       DRF 视图（signals / heatmap / config）

数据诚信边界（与 CLAUDE.md 红线一致）：
- 全部维度只用真实上游/本站快照数据推导，未知=null；
- 无数据源的维度在注册表显式 enabled=False 并写明原因，绝不伪造；
- 上游不可用时对象被跳过并记入 DetectorRun.degraded，不产生虚假信号。
"""
