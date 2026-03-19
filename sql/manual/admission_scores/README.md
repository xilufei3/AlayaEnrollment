# admission_scores

## 1. 表用途

用于保存各省各年份录取数据宽表，查询粒度为 `province + year`。

## 2. 数据来源

原始文件：

- `data/raw/structured/近三年录取情况.xlsx`

人工整理后的导入 SQL：

- `sql/manual/admission_scores/import.sql`

## 3. 字段说明

- `province`：省份名称
- `year`：年份，按 `INTEGER` 保存
- `admission_count`：总录取人数，按 `TEXT` 保存
- `regular_batch_count`：普通批次普通专业人数，按 `TEXT` 保存
- `joint_program_count`：普通批次中外合作人数，按 `TEXT` 保存
- `physics_review_count`：物理学综评人数，按 `TEXT` 保存
- `kcl_count`：KCL 联合医学院人数，按 `TEXT` 保存
- `max_score` / `avg_score` / `min_score`：分数字段，统一按 `TEXT` 保存
- `max_rank` / `avg_rank` / `min_rank`：位次字段，统一按 `TEXT` 保存
- `note`：备注

## 4. 执行顺序

1. 手工执行 `create.sql`
2. 手工检查或更新 `import.sql`
3. 手工执行 `import.sql`
4. 运行 `python -m src.knowledge.manage validate-sql`
5. 如需抽查，运行 `python -m src.knowledge.manage query-admission-scores --province 安徽 --year 2024`

## 5. 维护约束

- 一省一年只允许一行
- 缺失值统一用 `NULL`
- `year` 按 `INTEGER` 维护，其余字段统一按 `TEXT` 维护
- `import.sql` 只保存最终清洗后的可执行 SQL
- 不在业务代码中做自动建表和自动导入
