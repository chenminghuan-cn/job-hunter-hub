/**
 * 各信息源的结构差异调研笔记：页面展示 + 后续接入 Agent 时的字段映射参考。
 * 新渠道只要在 channels 表加一行，这里没写也没关系（页面会走通用提示）。
 */
export const CHANNEL_NOTES = {
  liepin: {
    kind: '结构化岗位站',
    fields: ['jobId', 'jobTitle', 'salary', 'city / dq', 'requireEduLevel', 'requireWorkYears', 'companyName', 'companyScale / companyStage', 'hrName / hrActiveTime'],
    pitfalls: ['需登录态 Cookie，反爬较严', '岗位会下架，需要定期回写状态'],
    mapping: 'source_job_id ← jobId；salary_raw ← salary；experience_req ← requireWorkYears',
  },
  boss: {
    kind: '结构化岗位站',
    fields: ['securityId', 'jobName', 'salaryDesc', 'cityName / areaDistrict', 'jobExperience', 'jobDegree', 'brandName / brandIndustry / brandScaleName', 'bossName / bossTitle', 'welfareList'],
    pitfalls: ['__zp_stoken__ 校验，token 易失效', '薪资是「K·薪数」文本，需解析'],
    mapping: 'source_job_id ← encryptJobId；publisher_name ← bossName；extra.welfare ← welfareList',
  },
  linkedin: {
    kind: '职业社交',
    fields: ['jobId', 'title', 'companyName', 'location', 'postedAt', 'employmentType', 'seniorityLevel', 'applyUrl'],
    pitfalls: ['国内网络不可直连，需要代理', '薪资字段通常为空', 'HR 联系方式不公开，联系人只能靠 InMail'],
    mapping: 'employment_type ← employmentType；posted_at ← postedAt',
  },
  maimai: {
    kind: '职场社区',
    fields: ['帖子正文（非结构化）', '发帖人 / 职级 / 公司认证', '评论区内推信息'],
    pitfalls: ['没有结构化岗位字段，需要 LLM 从正文抽取', '正文里常出现「私信」「评论区」等噪音'],
    mapping: 'title / company_name / city 需从正文抽取；联系人价值高于岗位字段',
  },
  xiaohongshu: {
    kind: '内容社区',
    fields: ['笔记标题 / 正文', '话题标签', '作者昵称', '图片（可能是岗位海报）'],
    pitfalls: ['招聘帖多为口播式描述，字段要抽取', '笔记会被删，需要尽快落库', '图片里的岗位信息需要 OCR/多模态识别'],
    mapping: 'source_job_id ← note_id；extra.images ← 图片列表；其余靠抽取',
  },
  x: {
    kind: '社交平台',
    fields: ['推文文本', '外链（careers 页）', '作者 handle', '发布时间'],
    pitfalls: ['信息密度低，通常要顺着外链二次抓取', '多语言，需统一成中文/英文两套字段'],
    mapping: 'url ← 外链；source_job_id ← tweet_id',
  },
  jike: {
    kind: '职场社区',
    fields: ['所属圈子（互联网 / 求职 / 产品经理…）', '帖子正文', '作者昵称与认证（公司/职位）', '话题标签', '评论区的内推与招人信息'],
    pitfalls: ['几乎全是非结构化正文，招聘帖混在闲聊里', '完整数据要走 App 端接口，网页版只给一部分', '帖子易删，看到就落库'],
    mapping: 'source_job_id ← post_id；title / company_name / city 从正文抽取；extra.circle ← 圈子名',
  },
  wechat_mp: {
    kind: '公众号文章',
    fields: ['文章标题 / 正文', '发布公众号', '发布时间', '正文内的岗位清单（一篇文章可能含多个岗位）'],
    pitfalls: ['一篇文章 → N 个岗位，必须拆分后逐个上报并各自带 source_job_id', '正文排版干扰强（表格/图片）'],
    mapping: 'source_job_id ← 文章 id + 序号；publisher_name ← 公众号名',
  },
}
