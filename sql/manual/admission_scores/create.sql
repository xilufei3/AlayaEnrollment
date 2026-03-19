-- 每个省份 + 年份对应一行数据。
-- year 使用 INTEGER，其余字段统一使用 TEXT，避免导入时因格式差异丢失原始信息。
CREATE TABLE IF NOT EXISTS admission_scores (
    province TEXT NOT NULL,              -- 省份名称，例如“安徽”
    year INTEGER NOT NULL,               -- 录取年份
    admission_count TEXT,                -- 总录取人数，可为空
    regular_batch_count TEXT,            -- 普通批次普通专业人数
    joint_program_count TEXT,            -- 普通批次中外合作人数
    physics_review_count TEXT,           -- 物理学综评人数
    kcl_count TEXT,                      -- KCL 联合医学院人数
    max_score TEXT,                      -- 最高分原文
    max_rank TEXT,                       -- 最高分位次原文
    avg_score TEXT,                      -- 平均分原文
    avg_rank TEXT,                       -- 平均分位次原文
    min_score TEXT,                      -- 最低分原文
    min_rank TEXT,                       -- 最低分位次原文
    note TEXT,                           -- 原始数据中的备注信息
    PRIMARY KEY (province, year)
);
