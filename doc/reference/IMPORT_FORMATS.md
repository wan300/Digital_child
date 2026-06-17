# 导入格式

第一版只支持文本优先导入：`txt`、`md`、`json`、`csv`。

## 文档导入 API

```http
POST /api/corpora/{corpus_id}/documents
Content-Type: application/json

{
  "filename": "diary-2026-05-31.md",
  "raw_text": "今天......",
  "content_type": "text/markdown"
}
```

也支持 `multipart/form-data` 上传单个文本文件。

## 聊天记录建议格式

```json
[
  {
    "timestamp": "2026-05-31T12:00:00+08:00",
    "speaker": "user",
    "content": "请记住：我喜欢简洁直接的回答。"
  },
  {
    "timestamp": "2026-05-31T12:00:04+08:00",
    "speaker": "persona",
    "content": "我会记住。"
  }
]
```

## 日记建议格式

```json
{
  "date": "2026-05-31",
  "title": "一次访谈后的记录",
  "content": "......"
}
```

## CSV 建议列

```text
timestamp,source,speaker,content
2026-05-31T12:00:00+08:00,chat,user,请记住：我喜欢简洁直接的回答。
```

## 后续扩展

PDF、DOCX、HTML、OCR 和复杂表格不在第一版范围内。需要这些能力时，可以引入 RAGFlow 或启用 LightRAG 的 MinerU/Docling parser。
