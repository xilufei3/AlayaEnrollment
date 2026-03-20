export type QuickPrompt = {
  label: string;
  question: string;
  hint: string;
};

export const BRAND_COPY = {
  title: "南方科技大学本科招生智能体",
  subtitle:
    "面向高中生与家长的招生咨询助手，可快速了解学校概况、综合评价、专业培养与校园生活。",
  description:
    "你好，欢迎咨询南科大招生。你可以直接提问，也可以从下方热门问题开始，快速进入报名、专业和校园生活等高频主题。",
  historyTitle: "咨询记录",
  historySubtitle: "查看最近的招生咨询对话",
  composerPlaceholder: "例如：南科大综合评价 631 模式怎么报名？",
  disclaimer: "内容基于招生资料整理，具体政策请以南科大本科招生网最新公告为准。",
  badges: [
    "覆盖学校概况、招生政策、专业与校园生活",
    "适合高中生、家长与升学咨询场景",
    "关键规则请以当年官方通知为准",
  ],
} as const;

export const APP_METADATA = {
  title: "南方科技大学本科招生智能体",
  description:
    "南方科技大学本科招生智能体，面向高中生和家长提供学校概况、招生政策、专业培养与校园生活咨询。",
} as const;

export const CONNECTION_COPY = {
  title: "招生智能体连接配置",
  description:
    "当前页面需要可用的服务地址与助手标识才能工作。若你正在本地调试，请确认前端环境变量或查询参数已正确配置。",
  apiUrlLabel: "服务地址",
  apiUrlHint: "用于连接招生智能体后端服务，可为本地或部署后的访问地址。",
  assistantIdLabel: "助手标识",
  assistantIdHint: "用于定位当前招生智能体实例，通常保持默认值即可。",
  apiKeyLabel: "访问密钥",
  apiKeyHint:
    "仅在目标服务启用了访问控制时需要填写。该值会保存在当前浏览器本地存储中。",
  submitLabel: "进入咨询界面",
} as const;

export const QUICK_PROMPTS: QuickPrompt[] = [
  {
    label: "综合评价报名",
    question: "南科大综合评价 631 模式怎么报名？有哪些关键时间点？",
    hint: "适合先了解报名路径、材料准备与时间节点。",
  },
  {
    label: "本科专业方向",
    question: "南科大有哪些本科专业？各自更适合什么样的学生？",
    hint: "快速对比专业方向、培养侧重和适配人群。",
  },
  {
    label: "书院与宿舍",
    question: "南科大的书院制和宿舍生活是怎样的？",
    hint: "想先感受校园氛围和居住体验时可以从这里开始。",
  },
  {
    label: "培养特色",
    question: "南科大小班教学、导师制和本科科研具体体现在哪里？",
    hint: "了解课程体验、导师支持和本科科研机会。",
  },
  {
    label: "录取省份政策",
    question: "如果我是广东考生，报考南科大时需要重点关注哪些招生政策？",
    hint: "适合结合本省政策、批次安排和报考策略来问。",
  },
  {
    label: "毕业去向",
    question: "南科大本科毕业后的深造和就业去向整体怎么样？",
    hint: "从升学去向、科研深造到就业表现做整体判断。",
  },
];
