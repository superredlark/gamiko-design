# Works / 作品

[English](#english) | [中文](#chinese)

---

<a name="english"></a>

Share your visual novels here. Submissions that pass the automatic check are **merged automatically**, with no waiting for a reviewer.

## How to submit

1. **Fork** this repository on GitHub.
2. In your fork, create a folder named after **your GitHub user name**, with one folder per work inside:

   ```
   works/<your-user-name>/
   ├── README.md              optional: a few words about yourself
   └── <work-name>/
       ├── README.md          required: title, author, and what others may do with the work
       ├── story_en.json      one or more stories (scene JSON format)
       ├── story_zh.json
       └── images/
           ├── 1.png
           └── 2.webp
   ```

3. Open a **pull request**. A bot checks it within a minute or two. If everything is fine, it merges the pull request. Otherwise it leaves a comment that says what to fix. Push the fix to the same branch and the check runs again.

You can update or delete your own works later in the same way.

## What the check requires

- You change files only inside `works/<your-user-name>/`. The folder name must match the account that opens the pull request; upper and lower case do not matter.
- Allowed files: `.json` `.md` `.txt` `.png` `.jpg` `.jpeg` `.webp`. Inside a work folder use only the top level and `images/`.
- Size: at most 5 MB per picture, 20 MB per work.
- Every work has a non-empty `README.md` and at least one story `.json`. Every story passes `python3 tools/gmkvn.py check` (see [the format](../docs/story-format.md)), and every `@b<id>` picture exists.

Check locally before submitting:

```sh
python3 tools/gmkvn.py check works/<you>/<work>/story_en.json
python3 tools/gmkvn.py preview works/<you>/<work>/story_en.json
```

## Rights

Only submit work you created or are allowed to share. Your work stays yours. Write in its `README.md` what others may do with it, for example "all rights reserved", "CC BY 4.0" or "free to play and share, no changes". Content that infringes others' rights or is inappropriate will be removed.

## README template

```markdown
# <Title>

- Author: <name or GitHub user name>
- Languages: English, 中文
- Pictures: <drawn by me / made with an AI tool / ...>
- License: <what others may do with this work>

<One or two sentences about the story.>
```

---

<a name="chinese"></a>

欢迎在这里分享你的视觉小说。通过自动检查的投稿会**自动合并**，不需要等人审核。

## 投稿步骤

1. 在 GitHub 上 **Fork** 本仓库。
2. 在你的 fork 里建一个以**你的 GitHub 用户名**命名的文件夹，每个作品一个子文件夹：

   ```
   works/<你的用户名>/
   ├── README.md              可选：介绍一下你自己
   └── <作品名>/
       ├── README.md          必需：标题、作者、别人可以怎样使用这个作品
       ├── story_zh.json      一个或多个故事（场景 JSON 格式）
       ├── story_en.json
       └── images/
           ├── 1.png
           └── 2.webp
   ```

3. 提交 **Pull Request**。一两分钟内机器人会完成检查：全部合格就自动合并；有问题会留言说明要改什么。把修改推送到同一个分支，检查会自动重跑。

以后修改或删除自己的作品，也按同样的方式提交。

## 检查规则

- 只能改动 `works/<你的用户名>/` 里的文件。文件夹名必须和提交 Pull Request 的账号一致，不区分大小写。
- 允许的文件：`.json` `.md` `.txt` `.png` `.jpg` `.jpeg` `.webp`。作品文件夹里只能用顶层和 `images/` 两层。
- 大小：每张图片不超过 5 MB，每个作品不超过 20 MB。
- 每个作品必须有非空的 `README.md` 和至少一个故事 `.json`。每个故事都要通过 `python3 tools/gmkvn.py check`（格式见[这里](../docs/story-format.zh.md)），所有 `@b<id>` 图片都要存在。

投稿前可以先在本地检查：

```sh
python3 tools/gmkvn.py check works/<你>/<作品>/story_zh.json
python3 tools/gmkvn.py preview works/<你>/<作品>/story_zh.json
```

## 权利

只投稿你自己创作或有权分享的内容。作品归你本人所有，请在作品的 `README.md` 里写明别人可以怎样使用它，例如「保留所有权利」「CC BY 4.0」「可自由游玩和转发，不可修改」。侵犯他人权利或不当的内容会被删除。

## README 模板

```markdown
# <标题>

- 作者：<名字或 GitHub 用户名>
- 语言：中文、English
- 图片：<本人绘制 / 用 AI 工具生成 / ……>
- 授权：<别人可以怎样使用这个作品>

<一两句话介绍这个故事。>
```
