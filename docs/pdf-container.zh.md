# 把故事打包成 PDF

[English](pdf-container.md)

Gamiko 把一整部视觉小说，连同剧本和全部图片，分享成**一个普通的 PDF 文件**。本文说明它是怎么做到的，并给出 [`tools/gmkvn.py`](../tools/gmkvn.py) 所写的公开格式的规范。

> **公开版说明。** Gamiko 官方文件的打包流程与本文描述的完全一致。区别在于，App 在把二进制数据放进 PDF 之前，还会经过一层私有协议的保护。因此 `gmkvn` 生成的文件 **Gamiko App 读不了**，Gamiko 官方的文件 `gmkvn` 也读不了。本仓库演示的是技术思路，不包含 App 的私有协议。

## 为什么用 PDF

- 传得出去。聊天软件、邮件、网盘、手机文件管理器都会原样转发 PDF，陌生的文件类型则常被拦截、改名或重新压缩。
- 谁都打得开。用普通阅读器打开时，看到的是一页正常的说明（标题和玩法），而不是报错。
- 数据随身携带。PDF 有标准的附件机制，故事不需要第二个文件。

## 打包流程

```
story.json + images/*.png
   │ 1. 收集      找出所有 "@b<id>" 背景 -> 读取 images/<id>.png
   │ 2. 扩展      story.images = { "<id>": <原始字节> }      JSON + 字节串类型
   │ 3. 信封      { dataType, ver, appType, appInnerId, story }
   │ 4. 序列化    二进制 JSON
   ▼ 5. 嵌入      作为附件放进一页 PDF
story.pdf
```

**1. 收集。** 扫描所有场景和步骤的背景，凡是 `"@b<id>"` 形式的取值都指向一张图片，图片放在故事旁边的 `images/<id>.png`。

**2. 给 JSON 加一个字节串类型。** 普通 JSON 没有二进制类型，用 base64 又会让每张图大三分之一。所以给 JSON 树多加一种取值类型：**字节串**，每张图片原样存进 `story.images`。PNG 的字节不解码、不重新编码、也不转 base64，解包得到的就是同一个文件。

**3. 信封。** 故事外面再包一层，让读取方知道里面装的是什么：

```json
{
  "dataType": "gmk",
  "ver": 1,
  "appType": "vn",
  "appInnerId": -2,
  "edition": "open",
  "story": { "title": "...", "serial": "...", "scenes": { }, "images": { "1": "<字节串>" } }
}
```

`edition: "open"` 只有 `gmkvn` 会写。

**4. 序列化成二进制 JSON。** 整棵树（包括字节串）写成一段紧凑的二进制数据。`gmkvn` 使用的格式见下文。

**5. 嵌入 PDF。** 这段二进制数据作为一个**嵌入文件**（PDF 标准附件），挂在一份普通的单页文档上。

### Gamiko App 有什么不同

第 1 到 3 步完全相同。第 4 步 App 用的是自己的二进制 JSON 布局，第 4 步和第 5 步之间数据还要经过一层私有的保护。官方文件可见的那一页是用 App 的字体画成的图片，而 `gmkvn` 默认直接嵌入文字。这些差别都不改变思路本身。

## GVJB：gmkvn 使用的二进制 JSON

所有多字节整数都是 **varint**：每字节存 7 位，低位组在前，除最后一个字节外最高位都置 1（LEB128）。

```
file  := "GVJB"  version:u8 (= 1)  value
value := tag:u8  payload
```

| 标签 | 类型 | 内容 |
|---|---|---|
| `0x00` | null | 无 |
| `0x01` | false | 无 |
| `0x02` | true | 无 |
| `0x03` | 整数 | zigzag varint：`n >= 0 -> 2n`，`n < 0 -> -2n-1` |
| `0x04` | 浮点数 | 8 字节 IEEE 754 双精度，大端 |
| `0x05` | 字符串 | varint 字节长度，接 UTF-8 |
| `0x06` | **字节串** | varint 长度，接原始字节。图片就靠这个扩展类型装进来 |
| `0x07` | 数组 | varint 元素个数，接这么多个值 |
| `0x08` | 对象 | varint 成员个数，每个成员是：键（varint 长度 + UTF-8）接值 |

例：`{"a": 1}` 写成

```
47 56 4A 42   01   08 01   01 61   03 02
"GVJB"        版本 对象n=1 键 "a"  整数 1（zigzag 后为 2）
```

整个文件必须恰好是一个值，后面不能有多余字节。对象的键保持原有顺序。

它和 CBOR、BSON 这类常见格式很接近。要说明的只有一点：「JSON + 字节串类型」就足以把整个故事装进一棵树。

## gmkvn 写出的 PDF 结构

| 对象 | 内容 |
|---|---|
| Catalog | `/Names << /EmbeddedFiles … >>`、`/AF [filespec]`、`/PageMode /UseAttachments`（多数阅读器打开时会显示附件面板） |
| Page | 一页 A5，包含标题、说明和页脚 |
| Filespec | `/F (story.gvnb)`，`/AFRelationship /Data` |
| EmbeddedFile | `/Subtype /application#2Fx-gvjb`，`/Params << /Size … /CheckSum <md5> /ModDate … >>`。数据流就是 GVJB 数据，**不压缩**（图片本身已经是压缩过的） |
| 字体 | 拉丁文字用 Helvetica（WinAnsi），中日文等其他文字用 **STSong-Light** + `UniGB-UCS2-H`。两者都是不嵌入的标准字体，所以文件很小。Acrobat 可能会提示下载亚洲语言字体包。拉丁字母、中文、日文假名、西里尔字母以外的文字（韩文、阿拉伯文、泰文等）请用 `--font` |

加 `--font some.ttf`（需要 Pillow）时，改用指定字体把这一页画成图片，官方文件就是这么做的。如果读者的 PDF 软件不支持中日文，请用这个选项。

**读取**不需要任何 PDF 库：找到内容以 `GVJB` 开头的嵌入文件数据流，按 `/Length` 读出字节，再解码即可。任何 PDF 阅读器也都能手动保存这个附件；`gmkvn unpack` 做的就是这件事，并把图片重新拆出来。

## 工具用法

只需要 Python 3.8 以上。Pillow 是可选的，只有 `--font` 用得到。

```sh
# 检查故事（不存在的场景、缺失的图片、走不到的场景……）
python3 tools/gmkvn.py check examples/lighthouse/story_zh.json

# story.json + images/ -> PDF
python3 tools/gmkvn.py pack examples/lighthouse/story_zh.json -o lighthouse.pdf
python3 tools/gmkvn.py pack story.json --desc "自定义的页面文字"
python3 tools/gmkvn.py pack story.json --font /path/to/NotoSansSC-Regular.ttf

# PDF -> story.json + images/（图片逐字节还原）
python3 tools/gmkvn.py unpack lighthouse.pdf lighthouse_out

# PDF（或 story.json）-> 一个自包含的 HTML 文件，并在浏览器中打开
python3 tools/gmkvn.py preview lighthouse.pdf
python3 tools/gmkvn.py preview examples/lighthouse/story_en.json --no-open
```

预览按 [story-format.zh.md](story-format.zh.md) 的规则播放故事：一屏一句、选项、分数与 `next_scenes`、结局、纯色背景、震屏效果，另有返回上一步的按钮。多语种的故事可以在 HTML 地址后加 `?lang=cn`（或 `en`、`zh`、`ja` 等）选择语种。
