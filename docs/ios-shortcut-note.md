# iOS 快捷指令触发 Life Note

这个仓库提供了 [`ios-shortcut-note.yml`](../.github/workflows/ios-shortcut-note.yml)。
它通过 `workflow_dispatch` 接收一个 `note` 输入，然后在 GitHub Actions 里用 `uv sync` + `uv run lfn` 执行 CLI，最后把更新后的 `README.md` 提交回 `main`。

## 工作流行为

- `note` 有值时，实际执行的是 `lfn --no-update --add "<note>"`
- `lfn --add` 会统一写成 `HH:MM | 内容`，时间使用 UTC+8 的 24 小时制，所以 workflow dispatch 触发的记录也会自动带时间
- `note` 为空时，实际执行的是 `lfn --no-update`
- workflow 会先执行 `uv sync --locked`，再通过 `uv run` 调用项目里的 CLI
- GitHub Actions 日志会打印 `inputs.note`、`github.event.inputs.note` 和整理后的 `note`，便于判断是快捷指令请求体没传到，还是 shell 清洗后变空
- workflow 自己负责提交 `README.md`，不会在 runner 里调用 `update.sh`
- workflow 运行环境固定为 UTF-8（`LANG/LC_ALL=C.UTF-8`，`PYTHONUTF8=1`）
- 同一分支上的请求会串行执行，避免两次手机触发互相打架

## GitHub API

你可以直接调用这个 endpoint：

```text
POST https://api.github.com/repos/yihong0618/life_note/actions/workflows/ios-shortcut-note.yml/dispatches
```

请求头：

- `Authorization: Bearer <YOUR_TOKEN>`
- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28`
- `Content-Type: application/json; charset=utf-8`

请求体：

```json
{
  "ref": "main",
  "inputs": {
    "note": "今天在手机上记一条"
  }
}
```

如果你只想补当天日期，不写内容：

```json
{
  "ref": "main",
  "inputs": {
    "note": ""
  }
}
```

## curl 示例

```bash
curl --request POST \
  --url https://api.github.com/repos/yihong0618/life_note/actions/workflows/ios-shortcut-note.yml/dispatches \
  --header "Accept: application/vnd.github+json" \
  --header "Authorization: Bearer <YOUR_TOKEN>" \
  --header "X-GitHub-Api-Version: 2022-11-28" \
  --header "Content-Type: application/json" \
  --data '{"ref":"main","inputs":{"note":"今天在手机上记一条"}}'
```

## iOS 快捷指令最小配置

1. 增加一个“询问输入”，类型选文本
2. 增加一个“获取 URL 内容”
3. URL 填：

```text
https://api.github.com/repos/yihong0618/life_note/actions/workflows/ios-shortcut-note.yml/dispatches
```

4. 方法选 `POST`
5. 请求头填上面那 4 个 header
6. 请求体选 JSON，内容填：

```json
{
  "ref": "main",
  "inputs": {
    "note": "快捷指令的输入结果"
  }
}
```

其中 `note` 的值绑定到前一步“询问输入”的结果即可。

## Token 说明

- 最省事的是 classic PAT，给 `repo` scope
- 如果你用 fine-grained token，只给这个仓库开能触发 Actions 的写权限即可
