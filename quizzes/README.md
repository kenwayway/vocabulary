# Quiz archive

每次出题存一个文件：`YYYY-MM-DD.md`。同一天多轮就往同一个文件里追加。

`pending.md` 是另一回事：它是**当前还没答完的那一轮**，只在手机答题流程里出现，
`vocab.py quiz close` 记完分就把它删掉。它不是存档，别往里写讲评。格式见
`CLAUDE.md` 的 Asking asynchronously 一节。

下面这个格式由 `vocab.py quiz close` 自动生成，但 `**评**` 那行它只留一个占位
注释——讲评还是要手写补进去，那才是这些文件值得留着的原因。

留着这些记录是为了能回头看：哪些词反复答错、你造的句子随时间有没有变自然、
哪类错误（搭配 / 语域 / 词义偏移）在重复出现。

格式：

```markdown
# 2026-08-08

## Round 1 — 14:32

### 1. serendipity  ·  Compose
**Q** 描述一次你在查别的 bug 时意外发现了什么。用 serendipity 造一句。
**A** > It was a serendipity that I found the memory leak.
**评** 记作 **wrong**。serendipity 是不可数名词，不说 "a serendipity"。
应该是 *It was pure serendipity that I found the memory leak* —— 或者用形容词，
*a serendipitous discovery*。词义方向是对的。
`level 2 → 0，明天再考`

### 2. tenuous  ·  Discriminate
...

---
**本轮**：1 correct / 1 wrong
```
