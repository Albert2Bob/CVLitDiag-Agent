import MarkdownIt from "markdown-it";
// 已禁用原始 HTML；markdown-it 也会拒绝 javascript:/vbscript:/不安全的 data URL。
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
// 上传或生成的远程图片不应发起未经请求的跟踪请求。
md.disable("image");
md.renderer.rules.table_open = () => '<div class="table-scroll"><table>';
md.renderer.rules.table_close = () => "</table></div>";
export const renderMarkdown = (text) =>
  md.render(typeof text === "string" ? text : "");
