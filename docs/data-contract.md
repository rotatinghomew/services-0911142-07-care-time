# 资料与统计口径

`diaries` 一行是某提供者某天的日记，家庭是抽样单位，提供者可同属一户；`stratum/psu/weight` 描述设计。`observed_start/observed_stop` 表示填报覆盖，`proxy` 为代填，不把覆盖外解释成空闲。`activities` 按 `[start,stop)` 记录分钟，跨午夜 stop 可超过1440，归属于开始日日记但分析须明确跨天处理且不能重复计入。同一人同时多项活动、不同人同照一个接收者都是合法事实。`primary/secondary/standby` 是角色而不是预先固定的数值权重。`design` 的5个工作日及2个周末日是目标周构成，不按回收份数决定。当前只显示填报分钟总和，未对并行活动或缺口作统计修正。

## 原始表

- `diaries`：256条示例，主键为 `diary`。字段：`diary`, `household`, `provider`, `day_type`, `area`, `day_start`, `observed_start`, `observed_stop`, `proxy`, `weight`, `stratum`, `psu`。
- `activities`：1024条示例，主键为 `activity`。字段：`activity`, `diary`, `start`, `stop`, `kind`, `recipient`, `task`。
- `design`：64条示例，主键为 `household`。字段：`household`, `workday_factor`, `weekend_factor`, `sampling_unit`。

## 版本与扩展

`fixtures/data.json` 是完整导入材料，`product.json` 是当前浏览器默认选择。全量导入校验后按规范化内容指纹保存，相同内容不重复建版本。原始事实不原地修改；资料修订形成新版本。`null` 表示明确未观测，不因筛选或合计自动变为0。

`care_time/domain.py` 是领域入口，现阶段仅做字段校验及资料描述；`service.py` 连接范围选择、数据版本与服务端计算后的存档；`storage.py` 管理不可变数据和保存材料；`web/app.js` 提供浏览和导出交互。保存的材料同时包含原数据与选择，打开旧材料不重算为新数据。新增分析不限内部组织方式，但不能丢失现有原始记录核对与历史材料读取能力。统计方法、模型选择和业务结论没有预设答案。
