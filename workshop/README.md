# 创作坊 (Workshop)

小红书内容批量创作工作区，按主题系列组织。

## 目录结构

```
workshop/
├── xian-winter/          # 长安冬韵 - 西安冬季攻略系列 (50篇)
│   ├── topics.json       # 主题配置文件
│   └── batch_generate.ps1 # 批量生成脚本
│
└── [future-series]/      # 未来更多系列...
```

## 使用方法

```powershell
# 从项目根目录运行某个系列
.\workshop\xian-winter\batch_generate.ps1

# 或进入目录运行
cd workshop\xian-winter
.\batch_generate.ps1
```

## 系列说明

### xian-winter (长安冬韵)
- **主题**: 西安冬季旅行攻略
- **数量**: 50 篇
- **受众**: 冬季出游者、摄影爱好者、美食探索者、文化爱好者等
