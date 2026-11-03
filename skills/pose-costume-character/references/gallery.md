# 从 Open Pose & Costume 选择参考

仅在用户给出库内编号、网站链接，或要求从库里挑选姿势／服饰时使用。用户已经给图片时无需访问网站。

- 工作台：https://hongye007.github.io/open-pose-costume/
- 公开索引：https://hongye007.github.io/open-pose-costume/data/catalog.json

## 元数据与选择

索引包含 `items` 和 `stats`。每条参考有 `id`、`code`、`kind`（`pose`／`costume`）、中英文 `title`、`keywords`、`category`、`variants`。

- 编号优先精确匹配 `id` 或 `code`。姿势示例：完整 ID `full_single_P047`，短编号 `P047`；服饰示例 `SPR-0050`。不要通过编号自行拼接图片 URL。
- 按文字查找时，在对应 `kind` 的中英文名称和关键词中匹配。多个差异明显的候选可给少量缩略图让用户选；用户已授权自行挑选时选最符合描述的候选并说明。
- 姿势的 `variants` 中有 `angle`、`label`、`thumbnail`、`image`、`original`；角度包括 `front`、`high`、`low`、`side`、`diag`，以实际存在的条目为准。
- 用户指定角度时精确选择；没有对应角度时说明并选可用视角，不捏造图片。未指定时默认正面或最能表达动作的已有视角。
- `thumbnail` 用于选图；实际生成使用该 variant 的 `original`。服饰的展示预览和 PNG 原图地址可能不同。

## 获取与素材范围

只获取当前选择所需的图片，不整库爬取。下载时校验响应确为可解码图片，确认没有误取 HTML 错误页；预览后给每张图片标清用途。下载原图不附带生图服务的 Authorization 头。

索引或上游图片不可用时保留已收到的参考；用户要求精确匹配时请其提供对应图片，不能静默换成另一张。

索引和原始图片保留其原有权利。此技能包不内置参考库图片或完整数据，也不改变素材授权；只将选定素材用于用户请求的创作。来源条款见 [项目 SOURCES.md](https://github.com/hongye007/open-pose-costume/blob/main/SOURCES.md) 和原站说明。
