# AlayaEnrollment 文档中心

本目录包含系统的部署、使用、数据导入与架构说明，建议按以下顺序阅读。

## 文档索引

| 文档 | 说明 |
|------|------|
| [部署指南 (deployment.md)](deployment.md) | 环境要求、Milvus 启动、后端/前端部署、环境变量配置 |
| [使用指南 (usage.md)](usage.md) | 聊天 API、前端使用、健康检查与常见操作 |
| [数据导入 (data-import.md)](data-import.md) | 从 AlayaData 到 Milvus 的导入流程、CLI 使用、故障排查 |
| [系统架构与 Milvus 层次](system-architecture-milvus-layers.md) | 整体架构、插入/检索链路与 Milvus 分层设计 |
| [AlayaData → Milvus 导入说明](milvus-ingestion-guide.md) | 导入组件说明、环境变量、执行命令与常见问题（详细版） |

## 规划与设计（plans/）

- [AlayaData 最小同步入库设计](plans/2026-03-08-alayadata-sync-ingestion-design.md)
- [AlayaData Sync Ingestion 实现计划](plans/2026-03-08-alayadata-sync-ingestion-implementation.md)

## 快速入口

- **首次部署**：阅读 [部署指南](deployment.md)，完成 Milvus、后端、前端启动。
- **日常使用**：阅读 [使用指南](usage.md)，了解聊天接口与前端访问方式。
- **导入业务数据**：阅读 [数据导入](data-import.md) 与 [Milvus 导入说明](milvus-ingestion-guide.md)。
