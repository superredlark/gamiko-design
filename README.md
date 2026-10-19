# Gamiko Design

[English](#english) | [中文](#chinese)

---

<a name="english"></a>

This repository is a place to share **technical material about visual novels** for [Gamiko](https://gamiko.app), and to show and discuss **works**.

## What's here

| Path | Content |
|---|---|
| [`docs/story-format.md`](docs/story-format.md) | The scene JSON format Gamiko reads for imported visual novels |
| [`docs/pdf-container.md`](docs/pdf-container.md) | How a whole story, script plus pictures, is packed into one ordinary PDF, and the open binary format used for it |
| [`tools/gmkvn.py`](tools/gmkvn.py) | Open-edition packer: story → PDF, PDF → story, and a one-file HTML preview. Python standard library only |
| [`examples/lighthouse/`](examples/lighthouse/) | *The Lighthouse in the Storm*: a complete 10-scene story with two endings, in English and Chinese |
| [`works/`](works/) | Stories shared by the community |

## Try it

```sh
python3 tools/gmkvn.py pack    examples/lighthouse/story_en.json -o lighthouse.pdf
python3 tools/gmkvn.py preview lighthouse.pdf
python3 tools/gmkvn.py unpack  lighthouse.pdf lighthouse_out
```

The PDF opens in any reader as a normal page, and carries the whole story as an attachment.

**Note:** PDFs made by `gmkvn` use the same technique as Gamiko's own files, but Gamiko adds a private protection protocol. The two are **not interchangeable**: the app cannot open `gmkvn` files and `gmkvn` cannot open the app's files. The tool is here to show how it works.

## Sharing works and joining the discussion

- **Works:** open a pull request that adds your story under `works/<your GitHub user name>/`. It is checked and **merged automatically**; see the [submission guide](works/README.md). You can also just post stories, scripts and artwork in [Discussions](https://github.com/superredlark/gamiko-design/discussions).
- **Questions and ideas** about the format or the tools: [Discussions](https://github.com/superredlark/gamiko-design/discussions).
- **Mistakes** in the docs or **bugs** in the tool: [Issues](https://github.com/superredlark/gamiko-design/issues). Pull requests are welcome.
- **Email:** support@tappole.com

## License

Code under `tools/` is MIT. Documentation under `docs/` is CC BY 4.0. Works shared here stay with their authors. Details are in [LICENSE](LICENSE).

---

<a name="chinese"></a>

本仓库用于分享 [Gamiko](https://gamiko.app) **视觉小说相关的技术资料**，并交流、展示**作品**。

## 内容

| 路径 | 内容 |
|---|---|
| [`docs/story-format.zh.md`](docs/story-format.zh.md) | Gamiko 读取外部视觉小说时使用的场景 JSON 格式 |
| [`docs/pdf-container.zh.md`](docs/pdf-container.zh.md) | 如何把剧本和图片整体打包进一个普通 PDF，以及所用的公开二进制格式 |
| [`tools/gmkvn.py`](tools/gmkvn.py) | 公开版打包工具：故事 → PDF、PDF → 故事，并可生成单文件 HTML 预览。只依赖 Python 标准库 |
| [`examples/lighthouse/`](examples/lighthouse/) | 《雨夜灯塔》：10 个场景、2 个结局的完整故事，含中英两版 |
| [`works/`](works/) | 大家分享的作品 |

## 试一试

```sh
python3 tools/gmkvn.py pack    examples/lighthouse/story_zh.json -o lighthouse.pdf
python3 tools/gmkvn.py preview lighthouse.pdf
python3 tools/gmkvn.py unpack  lighthouse.pdf lighthouse_out
```

这个 PDF 在任何阅读器里打开都是一页正常的说明，整个故事作为附件嵌在文件里。

**注意：** `gmkvn` 生成的 PDF 与 Gamiko 官方文件使用同样的技术，但官方文件额外加了一层私有的保护协议，两者**不互通**：App 打不开 `gmkvn` 的文件，`gmkvn` 也打不开 App 的文件。这个工具的用途是演示原理。

## 分享作品与参与讨论

- **作品：** 提交 Pull Request，把故事放进 `works/<你的 GitHub 用户名>/`，检查通过后会**自动合并**，见[投稿指南](works/README.md#chinese)。也可以直接在 [Discussions](https://github.com/superredlark/gamiko-design/discussions) 发布故事、剧本和美术作品。
- **格式或工具的问题与想法：** [Discussions](https://github.com/superredlark/gamiko-design/discussions)。
- **文档错误或工具 bug：** [Issues](https://github.com/superredlark/gamiko-design/issues)，欢迎提交 Pull Request。
- **邮件：** support@tappole.com

## 许可

`tools/` 下的代码采用 MIT 许可，`docs/` 下的文档采用 CC BY 4.0，在这里分享的作品归作者本人所有。详见 [LICENSE](LICENSE)。
