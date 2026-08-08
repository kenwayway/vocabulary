# Vocabulary

生词笔记本。每个词一个 Markdown 文件，Git 存历史，网页在手机上翻阅，
Claude 负责出题、批改和记录复习进度。

📖 **[打开笔记网页](https://kenwayway.github.io/vocabulary/)**

---

## 加一个新词

```bash
python scripts/vocab.py new serendipity --pos noun --tags "literary,chance"
```

这会从 `templates/word.md` 生成 `words/serendipity.md`，填好日期和初始复习状态。
接下来打开文件，把各个小节填上：

| 小节 | 写什么 |
| --- | --- |
| `## Definition` | 英文释义，尽量用自己的话，别抄词典 |
| `## In the wild` | **你真正遇到它的那句原文**，以及出处 |
| `## Etymology` | 词根词缀、同源词 —— 记住根，一串词就都记住了 |
| `## Word family` | 同族词：形容词、副词、动词形式 |
| `## Synonyms & nuance` | 不只是列举，要写清**差别在哪** |
| `## Collocations` | 它习惯搭配的词 |
| `## My sentences` | 你自己造的句子，每次复习都往里加一句 |
| `## Notes` | 记忆钩子、易混点 |

填完 commit + push，网页几分钟后自动更新。

`words/` 里的 `serendipity`、`equivocate`、`tenuous` 是示例，展示笔记该写到什么程度。
不需要的话直接删掉即可。

## 让 Claude 考你

开一个 Claude Code 会话，说「考我」就行。它会：

1. 从到期的词里挑 5 个（不够就用最久没复习的补上）
2. 出三种题：**自己造句** / **语境推义**（它造句、你解释）/ **近义词辨析**
3. 逐题用中文点评，指出搭配、语域、词义偏差
4. 把结果写回每个词的复习状态，并归档到 `quizzes/YYYY-MM-DD.md`

每天渥太华时间 12:30 会自动推一套题到你手机。

想让它帮你写笔记内容，明确说「帮我补全这个词」—— 默认它不会动你手写的正文。

## 命令

```bash
python scripts/vocab.py new <word>              # 从模板新建
python scripts/vocab.py due                     # 今天该复习哪些
python scripts/vocab.py due --limit 5 --fill    # 不够 5 个就补齐
python scripts/vocab.py review <word> --result correct|wrong
python scripts/vocab.py stats                   # 总量、熟悉度分布、正确率
python scripts/vocab.py validate                # 检查所有文件（CI 也跑这个）
python scripts/build_site.py                    # 生成 site/index.html
```

唯一依赖是 PyYAML：`pip install pyyaml`

## 复习节奏

熟悉度 0–6 级，对应间隔 **1 / 3 / 7 / 14 / 30 / 60 / 120** 天。
答对升一级，答错降两级并且明天再考。半对算错 —— 这才是间隔重复需要的信号。

## 网页

`site/index.html` 是单个自包含文件（数据内联，无外部请求），推送到 `main`
后由 GitHub Actions 自动构建发布。手机上「添加到主屏幕」之后离线也能看。

- **Browse** —— 搜索、按 due / 最近 / 最不熟 / 标签筛选，点开看完整笔记
- **Cards** —— 翻卡自测：只给英文释义和挖空的原文例句，翻面看词

翻卡模式的计分只在本轮有效、不会保存 —— 真正的复习进度由 Claude 出题时写入。

## 首次配置

网页需要仓库是 public：

1. `Settings → General → Danger Zone → Change visibility` → Public
2. `Settings → Pages → Source` → 选 **GitHub Actions**
