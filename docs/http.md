# 应用接口

服务绑定本地地址，输入输出为 UTF-8 JSON。错误输入为400，未找到对象为404，超过8MB请求为413。页面与服务端共用口径，前端不另算一份统计答案。

- `GET /health`：检查启动是否成功。
- `GET /api/context`：产品配置（含默认研究口径）、默认数据和已保存材料目录。
- `GET /api/data?revision=版本`：查看完整原始表。
- `POST /api/datasets`：传入 `label` 与完整 `data`，校验后返回不可变 `revision`。
- `POST /api/explore`：传入可选的 `revision` 和 `selection`，返回实际选择、资料指纹与 `view`。现有 view 的 summary、rows、series、notes 只用于描述。
- `POST /api/analyze`：传入可选的 `revision`、`selection` 与 `caliber`，返回规范化口径、资料指纹与 `analysis`。`analysis` 含覆盖统计、周负担均值与区间、加权分位数、群体差异、敏感性网格、提供者任务分担、接收端照护量、日记级明细与备注。范围中的日期类型筛选不作用于周估计；区域筛选按域估计处理。
- `GET /api/household?revision=版本&household=编号`：家庭时间轴材料，含各日期类型的日记原始记录、日记级测量与接收端并集段。家庭不存在为404。
- `POST /api/notebooks`：传入选择与 `title`，由服务端重新生成描述后保存，不接受客户端伪造结果；传入 `caliber` 时同时冻结研究估计与口径。
- `GET /api/notebooks` 与 `GET /api/notebooks/编号`：目录以及冻结资料、选择和结果。不含口径的旧记录照常打开。

新增分析可扩展接口，但已有导入、描述和历史读取仍供业务使用，不能静默改换其含义。
